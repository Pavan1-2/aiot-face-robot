import cv2
import os
import time
import zmq

try:
    from picamera2 import Picamera2
    USE_PICAMERA = True
except Exception:
    USE_PICAMERA = False
    print("picamera2 not found, using OpenCV")

STREAM_PORT = int(os.getenv("PI_STREAM_PORT", "5555"))
CAMERA_INDEX = int(os.getenv("PI_CAMERA_INDEX", "0"))
FRAME_WIDTH = int(os.getenv("PI_FRAME_WIDTH", "640"))
FRAME_HEIGHT = int(os.getenv("PI_FRAME_HEIGHT", "480"))
JPEG_QUALITY = int(os.getenv("PI_JPEG_QUALITY", "80"))
FPS = int(os.getenv("PI_STREAM_FPS", "30"))

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind(f"tcp://*:{STREAM_PORT}")

print("Raspberry Pi stream server starting...")

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
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

print(f"Streaming on port {STREAM_PORT}...")

try:
    while True:
        try:
            if USE_PICAMERA:
                frame = picam2.capture_array()
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
            
        except KeyboardInterrupt:
            print("Stopping stream...")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)
finally:
    if USE_PICAMERA:
        picam2.stop()
    else:
        cap.release()
    socket.close(0)
    context.term()
