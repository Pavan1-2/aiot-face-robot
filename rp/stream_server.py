import cv2
import os
import sys
import time

import zmq

# ---------------------------------------------------------------------------
# Optional: load .env so environment variables work when run directly
# (python-dotenv may not be installed on the Pi; fail silently if absent)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Optional: Raspberry Pi camera via picamera2
# ---------------------------------------------------------------------------
try:
    from picamera2 import Picamera2
    USE_PICAMERA = True
except Exception:
    USE_PICAMERA = False
    print("picamera2 not found, using OpenCV")

# ---------------------------------------------------------------------------
# Configuration from environment (with sane defaults)
# ---------------------------------------------------------------------------
STREAM_PORT   = int(os.getenv("PI_STREAM_PORT",    "5555"))
CAMERA_INDEX  = int(os.getenv("PI_CAMERA_INDEX",   "0"))
FRAME_WIDTH   = int(os.getenv("PI_FRAME_WIDTH",    "640"))
FRAME_HEIGHT  = int(os.getenv("PI_FRAME_HEIGHT",   "480"))
JPEG_QUALITY  = int(os.getenv("PI_JPEG_QUALITY",   "80"))
FPS           = max(1, int(os.getenv("PI_STREAM_FPS", "30")))  # guard against 0

# ---------------------------------------------------------------------------
# ZeroMQ publisher
# ---------------------------------------------------------------------------
context = zmq.Context()
socket  = context.socket(zmq.PUB)
socket.bind(f"tcp://*:{STREAM_PORT}")

print("Raspberry Pi stream server starting...")

# ---------------------------------------------------------------------------
# Camera initialisation
# ---------------------------------------------------------------------------
if USE_PICAMERA:
    picam2 = Picamera2()
    picam2.configure(
        picam2.create_video_configuration(
            main={"size": (FRAME_WIDTH, FRAME_HEIGHT)}
        )
    )
    picam2.start()
    print("Camera started via picamera2")
else:
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"ERROR: Could not open camera index {CAMERA_INDEX}. "
              "Check PI_CAMERA_INDEX or connect a camera.", file=sys.stderr)
        socket.close(linger=0)
        context.term()
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    print(f"Camera {CAMERA_INDEX} opened via OpenCV")

print(f"Streaming on port {STREAM_PORT} at {FPS} FPS...")

# ---------------------------------------------------------------------------
# Main streaming loop
# ---------------------------------------------------------------------------
try:
    while True:
        try:
            if USE_PICAMERA:
                frame = picam2.capture_array()
                # picamera2 may return RGB or RGBA depending on the format/OS version
                if frame.ndim == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                else:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            else:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    continue

            _, buffer = cv2.imencode(
                ".jpg", frame,
                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )

            socket.send(buffer.tobytes())
            time.sleep(1 / FPS)

        except Exception as e:
            print(f"Frame error: {e}")
            time.sleep(1)

except KeyboardInterrupt:
    print("\nStopping stream...")

finally:
    if USE_PICAMERA:
        picam2.stop()
    else:
        cap.release()
    socket.close(linger=0)
    context.term()
    print("Stream server stopped.")
