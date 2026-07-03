import cv2
import base64
import os
import threading
import time

import numpy as np
import zmq

PI_IP = os.getenv("PI_STREAM_HOST", "127.0.0.1")
PI_PORT = int(os.getenv("PI_STREAM_PORT", "5555"))

latest_pi_frame = None
pi_frame_lock = threading.Lock()
pi_connected = False
receiver_thread = None
receiver_active = False

def start_pi_receiver():
    global latest_pi_frame, pi_connected, receiver_active
    
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{PI_IP}:{PI_PORT}")
    socket.setsockopt(zmq.SUBSCRIBE, b"")
    socket.setsockopt(zmq.CONFLATE, 1)  # Only keep latest frame
    socket.setsockopt(zmq.RCVTIMEO, 3000)  # 3 second timeout
    
    print(f"Connecting to Pi at {PI_IP}:{PI_PORT}...")
    
    while receiver_active:
        try:
            buffer = socket.recv()
            np_arr = np.frombuffer(buffer, dtype=np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            
            with pi_frame_lock:
                latest_pi_frame = frame
            
            pi_connected = True
            
        except zmq.Again:
            pi_connected = False
            time.sleep(0.5)
        except Exception as e:
            pi_connected = False
            print(f"Pi stream error: {e}")
            time.sleep(1)

    socket.close(0)
    context.term()

def ensure_pi_receiver_started():
    global receiver_thread, receiver_active
    if receiver_thread and receiver_thread.is_alive():
        return
    receiver_active = True
    receiver_thread = threading.Thread(
        target=start_pi_receiver,
        daemon=True
    )
    receiver_thread.start()

def stop_pi_receiver():
    global receiver_active, pi_connected
    receiver_active = False
    pi_connected = False

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
