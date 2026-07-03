import threading

try:
    import pyaudio
    AUDIO_AVAILABLE = True
except Exception as exc:
    print(f"PyAudio not available: {exc} - audio passthrough disabled")
    pyaudio = None
    AUDIO_AVAILABLE = False

audio_active = False
audio_thread = None

CHUNK = 1024
CHANNELS = 1
RATE = 44100

def audio_passthrough_loop():
    global audio_active
    if not AUDIO_AVAILABLE:
        audio_active = False
        return
    
    p = pyaudio.PyAudio()
    
    try:
        stream_in = p.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )
        
        stream_out = p.open(
            format=pyaudio.paInt16,
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
    if not AUDIO_AVAILABLE:
        print("Audio passthrough skipped; PyAudio is not installed")
        return
    if audio_active:
        return
    audio_active = True
    audio_thread = threading.Thread(
        target=audio_passthrough_loop,
        daemon=True
    )
    audio_thread.start()

def stop_audio():
    global audio_active, audio_thread
    audio_active = False
    if audio_thread and audio_thread.is_alive():
        audio_thread.join(timeout=1)
    audio_thread = None

def is_audio_available():
    return AUDIO_AVAILABLE
