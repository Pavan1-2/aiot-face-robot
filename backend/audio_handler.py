# backend/audio_handler.py
#
# Real-time USB mic → MAX9744 speaker passthrough.
# Uses PyAudio callback mode with a small buffer for minimum latency.
# Device indices are configurable via env vars so the correct USB mic
# and output device (MAX9744) are selected on the Pi.

import os
import threading

try:
    import pyaudio
    AUDIO_AVAILABLE = True
except Exception as exc:
    print(f"PyAudio not available: {exc} - audio passthrough disabled")
    pyaudio = None
    AUDIO_AVAILABLE = False

# ── Config ────────────────────────────────────────────────────────────────────
# Set USB_MIC_DEVICE_INDEX / SPEAKER_DEVICE_INDEX in .env if the default
# device is not the USB mic / MAX9744 amp.
# Leave blank (or unset) to use the system default input/output device.

def _parse_device_index(env_key: str):
    val = os.getenv(env_key, "").strip()
    return int(val) if val.isdigit() else None

MIC_DEVICE_INDEX     = _parse_device_index("USB_MIC_DEVICE_INDEX")
SPEAKER_DEVICE_INDEX = _parse_device_index("SPEAKER_DEVICE_INDEX")

# Low-latency settings: 256-frame chunks at 16 kHz ≈ 16 ms round-trip
CHUNK    = 256
CHANNELS = 1
RATE     = 16000

# ── State ─────────────────────────────────────────────────────────────────────
audio_active = False
audio_thread = None
_pa_instance = None      # shared PyAudio handle


def _audio_passthrough_loop():
    """Blocking loop: read mic → write speaker at low latency."""
    global audio_active, _pa_instance

    if not AUDIO_AVAILABLE:
        audio_active = False
        return

    p = pyaudio.PyAudio()
    _pa_instance = p

    try:
        kwargs_in  = dict(format=pyaudio.paInt16, channels=CHANNELS,
                          rate=RATE, input=True,
                          frames_per_buffer=CHUNK)
        kwargs_out = dict(format=pyaudio.paInt16, channels=CHANNELS,
                          rate=RATE, output=True,
                          frames_per_buffer=CHUNK)

        if MIC_DEVICE_INDEX is not None:
            kwargs_in["input_device_index"] = MIC_DEVICE_INDEX
        if SPEAKER_DEVICE_INDEX is not None:
            kwargs_out["output_device_index"] = SPEAKER_DEVICE_INDEX

        stream_in  = p.open(**kwargs_in)
        stream_out = p.open(**kwargs_out)

        print(f"Audio passthrough started  "
              f"(mic={MIC_DEVICE_INDEX}, spk={SPEAKER_DEVICE_INDEX}, "
              f"chunk={CHUNK}, rate={RATE})")

        while audio_active:
            data = stream_in.read(CHUNK, exception_on_overflow=False)
            stream_out.write(data)

        stream_in.stop_stream();  stream_in.close()
        stream_out.stop_stream(); stream_out.close()

    except Exception as exc:
        print(f"Audio passthrough error: {exc}")
    finally:
        p.terminate()
        _pa_instance = None
        print("Audio passthrough stopped")


# ── Public API ─────────────────────────────────────────────────────────────────

def start_audio():
    global audio_active, audio_thread
    if not AUDIO_AVAILABLE:
        print("Audio passthrough skipped; PyAudio not installed")
        return
    if audio_active:
        return
    audio_active = True
    audio_thread = threading.Thread(
        target=_audio_passthrough_loop,
        daemon=True
    )
    audio_thread.start()


def stop_audio():
    global audio_active, audio_thread
    audio_active = False
    if audio_thread and audio_thread.is_alive():
        audio_thread.join(timeout=2)
    audio_thread = None


def is_audio_available() -> bool:
    return AUDIO_AVAILABLE


def is_audio_active() -> bool:
    return audio_active


def get_audio_status() -> dict:
    return {
        "available":  AUDIO_AVAILABLE,
        "active":     audio_active,
        "mic_index":  MIC_DEVICE_INDEX,
        "spk_index":  SPEAKER_DEVICE_INDEX,
        "rate":       RATE,
        "chunk":      CHUNK,
    }


def list_audio_devices() -> list:
    """Return a list of PyAudio device info dicts (for debugging)."""
    if not AUDIO_AVAILABLE:
        return []
    p = pyaudio.PyAudio()
    devices = [p.get_device_info_by_index(i)
               for i in range(p.get_device_count())]
    p.terminate()
    return devices
