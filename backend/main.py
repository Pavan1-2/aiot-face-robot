import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from servo_controller import (
    recalibrate_to_center,
    emergency_stop,
    get_current_state,
    get_all_robot_states,
    get_robot_enabled_state,
    set_robot_enabled,
    blink,
)
from face_tracking import (
    get_face_tracking_backend,
    start_tracking,
    stop_tracking,
    get_faculty_frame_base64,
    is_face_tracking_available,
)
from pi_stream import (
    ensure_pi_receiver_started,
    get_pi_frame_base64,
    is_pi_connected,
    stop_pi_receiver,
)
from vinu_engine import (
    GROQ_API_KEY,
    start_vinu,
    stop_vinu,
    query_vinu,
    get_vinu_camera_frame,
    get_vinu_status,
    clear_history,
)
from audio_handler import (
    is_audio_available,
    is_audio_active,
    get_audio_status,
    list_audio_devices,
    start_audio,
    stop_audio,
)
from vinu_voice import handle_voice_session, get_voice_state

app = FastAPI(title="AIoT Face Robot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

current_mode = "idle"
mode_lock = asyncio.Lock()


@app.on_event("startup")
async def startup():
    ensure_pi_receiver_started()
    recalibrate_to_center()


@app.on_event("shutdown")
async def shutdown():
    stop_tracking()
    stop_vinu()
    stop_audio()
    stop_pi_receiver()


# ─── STATUS ───────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    return {
        "mode": current_mode,
        "pi_connected": is_pi_connected(),
        "vinu_status": get_vinu_status(),
        "vinu_configured": bool(GROQ_API_KEY),
        "audio_available": is_audio_available(),
        "audio_active": is_audio_active(),
        "face_tracking_available": is_face_tracking_available(),
        "face_tracking_backend": get_face_tracking_backend(),
        "voice_state": get_voice_state(),
        # backward-compatible single-robot servo view
        "servos": get_current_state(),
        # multi-robot data
        "robots": get_robot_enabled_state(),
        "robot_servos": get_all_robot_states(),
    }


# ─── MODE CONTROL ─────────────────────────────────────────────────────────────

@app.post("/api/mode/tracking")
async def mode_tracking():
    global current_mode
    async with mode_lock:
        stop_vinu()
        start_tracking()
        start_audio()
        current_mode = "tracking"
    return {"mode": "tracking", "status": "started"}


@app.post("/api/mode/vinu")
async def mode_vinu():
    global current_mode
    async with mode_lock:
        stop_tracking()
        stop_audio()
        start_vinu()
        current_mode = "vinu"
    return {"mode": "vinu", "status": "started"}


@app.post("/api/mode/idle")
async def mode_idle():
    global current_mode
    async with mode_lock:
        stop_tracking()
        stop_vinu()
        stop_audio()
        recalibrate_to_center()
        current_mode = "idle"
    return {"mode": "idle", "status": "stopped"}


# ─── SERVO CONTROLS ───────────────────────────────────────────────────────────

@app.post("/api/servo/center")
async def center():
    recalibrate_to_center()
    return {"status": "centered"}


@app.post("/api/servo/estop")
async def estop():
    global current_mode
    stop_tracking()
    stop_vinu()
    stop_audio()
    emergency_stop()
    current_mode = "idle"
    return {"status": "emergency_stopped"}


@app.post("/api/servo/blink")
async def do_blink():
    blink()
    return {"status": "blinked"}


# ─── ROBOT ENABLE / DISABLE ───────────────────────────────────────────────────

@app.get("/api/robots")
async def get_robots():
    return get_robot_enabled_state()


@app.post("/api/robots/{robot_id}/enable")
async def enable_robot(robot_id: int):
    if robot_id not in (1, 2, 3):
        return {"error": f"Invalid robot_id {robot_id}. Must be 1, 2, or 3."}, 400
    set_robot_enabled(robot_id, True)
    return {"robot": robot_id, "enabled": True}


@app.post("/api/robots/{robot_id}/disable")
async def disable_robot(robot_id: int):
    if robot_id not in (1, 2, 3):
        return {"error": f"Invalid robot_id {robot_id}. Must be 1, 2, or 3."}, 400
    set_robot_enabled(robot_id, False)
    return {"robot": robot_id, "enabled": False}


# ─── AUDIO PASSTHROUGH ────────────────────────────────────────────────────────

@app.post("/api/audio/passthrough/on")
async def audio_on():
    """Enable real-time USB mic → MAX9744 speaker passthrough."""
    start_audio()
    return get_audio_status()


@app.post("/api/audio/passthrough/off")
async def audio_off():
    """Disable audio passthrough."""
    stop_audio()
    return get_audio_status()


@app.get("/api/audio/status")
async def audio_status():
    return get_audio_status()


@app.get("/api/audio/devices")
async def audio_devices():
    """List all PyAudio devices (useful for finding USB mic / MAX9744 indices)."""
    devices = list_audio_devices()
    return [
        {
            "index": d["index"],
            "name": d["name"],
            "max_input_channels": d["maxInputChannels"],
            "max_output_channels": d["maxOutputChannels"],
        }
        for d in devices
    ]


# ─── VINU ─────────────────────────────────────────────────────────────────────

@app.post("/api/vinu/query")
async def vinu_query(data: dict):
    text = data.get("text", "")
    use_camera = data.get("use_camera", False)
    response = await query_vinu(text, use_camera)
    return {"response": response}


@app.post("/api/vinu/clear")
async def vinu_clear():
    clear_history()
    return {"status": "cleared"}


# ─── WEBSOCKETS ───────────────────────────────────────────────────────────────

@app.websocket("/ws/classroom-feed")
async def classroom_feed(websocket: WebSocket):
    await websocket.accept()
    print("Classroom feed WebSocket connected")
    try:
        while True:
            frame = get_pi_frame_base64()
            if frame:
                await websocket.send_text(frame)
            await asyncio.sleep(1 / 25)  # 25 fps
    except WebSocketDisconnect:
        print("Classroom feed disconnected")


@app.websocket("/ws/faculty-feed")
async def faculty_feed(websocket: WebSocket):
    await websocket.accept()
    print("Faculty feed WebSocket connected")
    try:
        while True:
            frame = get_faculty_frame_base64()
            if frame:
                await websocket.send_text(frame)
            await asyncio.sleep(1 / 25)
    except WebSocketDisconnect:
        print("Faculty feed disconnected")


@app.websocket("/ws/vinu-feed")
async def vinu_feed(websocket: WebSocket):
    await websocket.accept()
    print("VINU feed WebSocket connected")
    try:
        while True:
            frame = get_vinu_camera_frame()
            if frame:
                await websocket.send_text(frame)
            await asyncio.sleep(1 / 15)
    except WebSocketDisconnect:
        print("VINU feed disconnected")


@app.websocket("/ws/servo-status")
async def servo_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            payload = {
                "robots": get_robot_enabled_state(),
                "robot_servos": get_all_robot_states(),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/voice-chat")
async def voice_chat(websocket: WebSocket):
    """
    Voice chat WebSocket for VINU.
    Browser streams mic audio (WebM/Opus) → Whisper STT → VINU LLM → gTTS speaker reply.
    """
    await websocket.accept()
    print("Voice chat WebSocket connected")
    try:
        await handle_voice_session(websocket)
    except WebSocketDisconnect:
        pass
    finally:
        print("Voice chat WebSocket disconnected")
