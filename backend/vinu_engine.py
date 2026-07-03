import asyncio
import base64
import os
import shutil
import threading
import subprocess
import tempfile

import cv2
from gtts import gTTS

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL = os.getenv("VINU_MODEL", "llama-3.2-11b-vision-preview")
CAMERA_INDEX = int(os.getenv("FACULTY_CAMERA_INDEX", "0"))
ENABLE_TTS = os.getenv("VINU_ENABLE_TTS", "1").lower() not in {"0", "false", "no"}

SYSTEM_PROMPT = """You are VINU (Virtual Instructional Network Unit), 
an AI teaching assistant for faculty at Ramaiah Institute of Technology. 
You help faculty with:
- Academic queries and explanations
- Object identification from camera
- Lesson planning and content generation
Keep responses concise and educational."""

conversation_history = []
vinu_active = False
vinu_camera = None
vinu_status = "idle"
camera_lock = threading.Lock()

def get_vinu_status():
    return vinu_status

def start_vinu():
    global vinu_active, vinu_camera
    vinu_active = True
    with camera_lock:
        if vinu_camera is None:
            vinu_camera = cv2.VideoCapture(CAMERA_INDEX)
            vinu_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            vinu_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    print("VINU mode started")

def stop_vinu():
    global vinu_active, vinu_camera
    vinu_active = False
    with camera_lock:
        if vinu_camera:
            vinu_camera.release()
            vinu_camera = None
    print("VINU mode stopped")

def capture_frame_base64():
    with camera_lock:
        if not vinu_camera:
            return None
        ret, frame = vinu_camera.read()
    if not ret:
        return None
    _, buffer = cv2.imencode('.jpg', frame)
    return base64.b64encode(buffer).decode('utf-8')

def get_vinu_camera_frame():
    with camera_lock:
        if not vinu_camera:
            return None
        ret, frame = vinu_camera.read()
    if not ret:
        return None
    _, buffer = cv2.imencode(
        '.jpg', frame,
        [cv2.IMWRITE_JPEG_QUALITY, 75]
    )
    return base64.b64encode(buffer).decode('utf-8')

async def query_vinu(text_query: str, use_camera: bool = False):
    global vinu_status, conversation_history

    if not GROQ_API_KEY:
        return "VINU is not configured. Set GROQ_API_KEY in your environment and restart the backend."
    if not text_query.strip():
        return "Please enter a question for VINU."

    return await asyncio.to_thread(_query_vinu_sync, text_query, use_camera)

def _query_vinu_sync(text_query: str, use_camera: bool = False):
    global vinu_status, conversation_history

    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        
        vinu_status = "thinking"
        
        # Build message content
        if use_camera:
            image_b64 = capture_frame_base64()
            if image_b64:
                content = [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        }
                    },
                    {"type": "text", "text": text_query}
                ]
            else:
                content = text_query
        else:
            content = text_query
        
        # Add to history
        conversation_history.append({
            "role": "user",
            "content": content
        })
        
        # Query Groq
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *conversation_history[-10:]  # Keep last 10 turns
            ],
            max_tokens=500,
            temperature=0.7
        )
        
        reply = response.choices[0].message.content.strip()
        
        # Add reply to history
        conversation_history.append({
            "role": "assistant",
            "content": reply
        })
        
        # Speak response
        vinu_status = "speaking"
        speak_response(reply)
        
        vinu_status = "idle"
        return reply
        
    except Exception as e:
        vinu_status = "idle"
        print(f"VINU error: {e}")
        return f"Error: {str(e)}"

def speak_response(text):
    if not ENABLE_TTS:
        return
    player = shutil.which("mpg123")
    if not player:
        print("TTS skipped: mpg123 is not installed")
        return

    output_path = os.path.join(tempfile.gettempdir(), "vinu_reply.mp3")
    try:
        tts = gTTS(text=text, lang='en', tld='co.in')
        tts.save(output_path)
        subprocess.Popen(
            [player, "-q", output_path]
        ).wait()
    except Exception as e:
        print(f"TTS error: {e}")

def clear_history():
    global conversation_history
    conversation_history = []
