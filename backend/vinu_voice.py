# backend/vinu_voice.py
#
# VINU voice chat: browser streams mic audio → Groq Whisper STT → VINU LLM → TTS reply.
#
# Flow:
#   1. Frontend opens WebSocket /ws/voice-chat
#   2. Backend sends status updates over the socket
#   3. Frontend sends binary PCM/WebM audio chunks
#   4. On "stop" signal, backend transcribes with Whisper, queries VINU, speaks reply
#   5. Backend sends final transcript + reply as JSON

import asyncio
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")

# Voice chat state (shared across all connections)
_voice_state = "idle"        # idle | recording | transcribing | thinking | speaking
_voice_lock  = threading.Lock()
_listeners: list = []        # active WebSocket connections to broadcast to


def get_voice_state() -> str:
    return _voice_state


def _set_state(state: str, extra: dict = None):
    global _voice_state
    with _voice_lock:
        _voice_state = state
    payload = {"state": state, **(extra or {})}
    _broadcast(json.dumps(payload))
    print(f"[voice] {state}")


def _broadcast(message: str):
    """Push a message to all connected voice-status WebSockets."""
    dead = []
    for ws in list(_listeners):
        try:
            # Schedule send in the event loop the websocket lives in
            loop = ws._loop if hasattr(ws, "_loop") else None
            if loop and not loop.is_closed():
                asyncio.run_coroutine_threadsafe(ws.send_text(message), loop)
            else:
                dead.append(ws)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _listeners.remove(ws)
        except ValueError:
            pass


def register_ws(ws):
    ws._loop = asyncio.get_event_loop()
    _listeners.append(ws)


def unregister_ws(ws):
    try:
        _listeners.remove(ws)
    except ValueError:
        pass


async def handle_voice_session(websocket):
    """
    WebSocket handler for /ws/voice-chat.

    Protocol:
      • Backend → Client: JSON status messages
          {"state": "idle|recording|transcribing|thinking|speaking",
           "transcript": "...", "reply": "..."}
      • Client → Backend: binary audio data chunks (WebM/Opus from MediaRecorder)
          OR text "STOP" to end recording and trigger transcription
    """
    from vinu_engine import query_vinu

    register_ws(websocket)
    await websocket.send_text(json.dumps({"state": _voice_state}))

    audio_chunks: list[bytes] = []
    recording = False

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            # Binary chunk = audio data from browser MediaRecorder
            if "bytes" in message and message["bytes"]:
                if not recording:
                    recording = True
                    audio_chunks = []
                    _set_state("recording")
                audio_chunks.append(message["bytes"])
                continue

            # Text messages
            text = message.get("text", "")
            if not text:
                continue

            if text == "START":
                recording = True
                audio_chunks = []
                _set_state("recording")

            elif text == "STOP" and recording:
                recording = False
                _set_state("transcribing")

                transcript = await asyncio.to_thread(
                    _transcribe, b"".join(audio_chunks)
                )

                if transcript:
                    await websocket.send_text(json.dumps({
                        "state": "thinking",
                        "transcript": transcript
                    }))
                    _set_state("thinking", {"transcript": transcript})

                    reply = await query_vinu(transcript, use_camera=False)

                    _set_state("speaking", {"transcript": transcript, "reply": reply})
                    await websocket.send_text(json.dumps({
                        "state": "speaking",
                        "transcript": transcript,
                        "reply": reply
                    }))

                    # Speak reply through server speaker (gTTS → mpg123)
                    await asyncio.to_thread(_speak, reply)

                    await websocket.send_text(json.dumps({
                        "state": "idle",
                        "transcript": transcript,
                        "reply": reply
                    }))
                    _set_state("idle")
                else:
                    await websocket.send_text(json.dumps({
                        "state": "idle",
                        "error": "Could not transcribe audio. Please try again."
                    }))
                    _set_state("idle")

                audio_chunks = []

    except Exception as exc:
        print(f"[voice] WebSocket error: {exc}")
    finally:
        unregister_ws(websocket)
        _set_state("idle")


def _transcribe(audio_bytes: bytes) -> str:
    """Send audio to Groq Whisper and return the transcript."""
    if not GROQ_API_KEY:
        return ""
    if not audio_bytes:
        return ""

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        # Write to a temp file — Groq SDK requires a file-like object with a name
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=f,
                    response_format="text",
                )
            return str(result).strip()
        finally:
            os.unlink(tmp_path)

    except Exception as exc:
        print(f"[voice] Whisper error: {exc}")
        return ""


def _speak(text: str):
    """Speak text through the server speaker using the tracked speak_response in vinu_engine."""
    from vinu_engine import speak_response
    speak_response(text)
