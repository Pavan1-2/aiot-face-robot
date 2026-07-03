# backend/main.py

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import json

# Import modules
from servo_controller import (
    recalibrate_to_center,
    emergency_stop,
    get_current_state,
    blink
)
from face_tracking import (
    start_tracking,
    stop_tracking,
    get_faculty_frame_base64
)
from pi_stream import (
    get_pi_frame_base64,
    is_pi_connected
)
from vinu_engine import (
    start_vinu,
    stop_vinu,
    query_vinu,
    get_vinu_camera_frame,
    get_vinu_status,
    clear_history
)
from audio_handler import start_audio, stop_audio

app = FastAPI(title="AIoT Face Robot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

current_mode = "idle"

# ─── STATUS ───────────────────────────────────

@app.get("/api/status")
async def get_status():
    return {
        "mode": current_mode,
        "pi_connected": is_pi_connected(),
        "vinu_status": get_vinu_status(),
        "servos": get_current_state()
    }

# ─── MODE CONTROL ─────────────────────────────

@app.post("/api/mode/tracking")
async def mode_tracking():
    global current_mode
    stop_vinu()
    start_tracking()
    start_audio()
    current_mode = "tracking"
    return {"mode": "tracking", "status": "started"}

@app.post("/api/mode/vinu")
async def mode_vinu():
    global current_mode
    stop_tracking()
    stop_audio()
    start_vinu()
    current_mode = "vinu"
    return {"mode": "vinu", "status": "started"}

@app.post("/api/mode/idle")
async def mode_idle():
    global current_mode
    stop_tracking()
    stop_vinu()
    stop_audio()
    recalibrate_to_center()
    current_mode = "idle"
    return {"mode": "idle", "status": "stopped"}

# ─── SERVO CONTROLS ───────────────────────────

@app.post("/api/servo/center")
async def center():
    recalibrate_to_center()
    return {"status": "centered"}

@app.post("/api/servo/estop")
async def estop():
    stop_tracking()
    stop_audio()
    emergency_stop()
    global current_mode
    current_mode = "idle"
    return {"status": "emergency_stopped"}

@app.post("/api/servo/blink")
async def do_blink():
    blink()
    return {"status": "blinked"}

# ─── VINU ─────────────────────────────────────

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

# ─── WEBSOCKETS ───────────────────────────────

@app.websocket("/ws/classroom-feed")
async def classroom_feed(websocket: WebSocket):
    await websocket.accept()
    print("Classroom feed WebSocket connected")
    try:
        while True:
            frame = get_pi_frame_base64()
            if frame:
                await websocket.send_text(frame)
            await asyncio.sleep(1/25)  # 25fps
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
            await asyncio.sleep(1/25)
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
            await asyncio.sleep(1/15)  # 15fps enough for object detection
    except WebSocketDisconnect:
        print("VINU feed disconnected")

@app.websocket("/ws/servo-status")
async def servo_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            state = get_current_state()
            await websocket.send_text(json.dumps(state))
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
