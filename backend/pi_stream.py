# backend/pi_stream.py

import zmq
import cv2
import numpy as np
import threading
import base64

PI_IP = "10.141.139.118"  # CHANGE THIS to your Pi IP
PI_PORT = 5555

latest_pi_frame = None
pi_frame_lock = threading.Lock()
pi_connected = False

def start_pi_receiver():
    global latest_pi_frame, pi_connected
    
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{PI_IP}:{PI_PORT}")
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.CONFLATE, 1)  # Only keep latest frame
    socket.setsockopt(zmq.RCVTIMEO, 3000)  # 3 second timeout
    
    print(f"Connecting to Pi at {PI_IP}:{PI_PORT}...")
    
    while True:
        try:
            buffer = socket.recv()
            np_arr = np.frombuffer(buffer, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            with pi_frame_lock:
                latest_pi_frame = frame
            
            pi_connected = True
            
        except zmq.Again:
            pi_connected = False
            print("Pi stream timeout - retrying...")
        except Exception as e:
            pi_connected = False
            print(f"Pi stream error: {e}")

def get_pi_frame_base64():
    with pi_frame_lock:
        if latest_pi_frame is None:
            return None
        _, buffer = cv2.imencode(
            '.jpg',
            latest_pi_frame,
            [cv2.IMWRITE_JPEG_QUALITY, 80]
        )
        return base64.b64encode(buffer).decode('utf-8')

def is_pi_connected():
    return pi_connected

# Start receiver thread automatically
receiver_thread = threading.Thread(
    target=start_pi_receiver,
    daemon=True
)
receiver_thread.start()
