# backend/audio_handler.py

import pyaudio
import threading
import numpy as np

audio_active = False
audio_thread = None

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

def audio_passthrough_loop():
    global audio_active
    
    p = pyaudio.PyAudio()
    
    try:
        stream_in = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        stream_out = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            output=True,
            frames_per_buffer=CHUNK
        )
        
        print("Audio passthrough started")
        
        while audio_active:
            data = stream_in.read(CHUNK, exception_on_overflow=False)
            stream_out.write(data)
        
        stream_in.stop_stream()
        stream_out.stop_stream()
        stream_in.close()
        stream_out.close()
        
    except Exception as e:
        print(f"Audio error: {e}")
    finally:
        p.terminate()
        print("Audio passthrough stopped")

def start_audio():
    global audio_active, audio_thread
    if audio_active:
        return
    audio_active = True
    audio_thread = threading.Thread(
        target=audio_passthrough_loop,
        daemon=True
    )
    audio_thread.start()

def stop_audio():
    global audio_active
    audio_active = False

