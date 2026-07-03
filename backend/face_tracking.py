import cv2
import os
import tempfile
import threading
import time

from servo_controller import write_servo, recalibrate_to_center

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "matplotlib"))

try:
    import mediapipe as mp
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.7
    )
    FACE_TRACKING_AVAILABLE = True
    FACE_TRACKING_BACKEND = "mediapipe"
except Exception as exc:
    face_mesh = None
    face_cascade = cv2.CascadeClassifier(
        os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    )
    FACE_TRACKING_AVAILABLE = not face_cascade.empty()
    FACE_TRACKING_BACKEND = "opencv-haar" if FACE_TRACKING_AVAILABLE else "none"
    print(f"MediaPipe FaceMesh unavailable: {exc} - using {FACE_TRACKING_BACKEND}")

# State
tracking_active = False
tracking_thread = None
camera = None
latest_faculty_frame = None
frame_lock = threading.Lock()
camera_lock = threading.Lock()

# Smoothing
smooth_state = {"yaw": 90.0, "pitch": 90.0, "eye": 90.0}
alpha = 0.4
MAX_DELTA = 20
CAMERA_INDEX = int(os.getenv("FACULTY_CAMERA_INDEX", "0"))

# Constants
NECK_LEFT = 30;   NECK_RIGHT = 150
NECK_UP = 35;     NECK_DOWN = 145
EYE_LEFT = 40;    EYE_RIGHT = 140

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def map_range(val, in_min, in_max, out_min, out_max):
    return clamp(
        (val - in_min) * (out_max - out_min) / 
        (in_max - in_min + 1e-6) + out_min,
        min(out_min, out_max),
        max(out_min, out_max)
    )

def vel_cap(raw, smooth):
    return smooth + clamp(
        raw - smooth, 
        -MAX_DELTA, 
        MAX_DELTA
    )

def tracking_loop():
    global latest_faculty_frame, camera, tracking_active
    
    with camera_lock:
        camera = cv2.VideoCapture(CAMERA_INDEX)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        camera.set(cv2.CAP_PROP_FPS, 30)
    
    print("Face tracking started")
    
    while tracking_active:
        with camera_lock:
            if camera is None:
                break
            ret, frame = camera.read()
        if not ret:
            time.sleep(0.1)
            continue
        
        results = None
        if FACE_TRACKING_AVAILABLE:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)
        
        if results and results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark
            
            nose      = lm[1]
            left_eye  = lm[33]
            right_eye = lm[263]
            forehead  = lm[10]
            chin      = lm[152]
            
            # Calculate ratios
            eye_width = right_eye.x - left_eye.x
            if eye_width > 1e-4:
                yaw_ratio = map_range(
                    (nose.x - left_eye.x) / eye_width,
                    0.15, 0.85, 0.0, 1.0
                )
            else:
                yaw_ratio = 0.5
            
            face_height = chin.y - forehead.y
            if face_height > 1e-4:
                pitch_ratio = map_range(
                    (nose.y - forehead.y) / face_height,
                    0.30, 0.70, 0.0, 1.0
                )
            else:
                pitch_ratio = 0.5
            
            # Raw servo values
            raw_yaw   = NECK_LEFT + (NECK_RIGHT - NECK_LEFT) * yaw_ratio
            raw_pitch = NECK_UP   + (NECK_DOWN  - NECK_UP)   * pitch_ratio
            raw_eye   = EYE_LEFT  + (EYE_RIGHT  - EYE_LEFT)  * yaw_ratio
            
            # Smooth
            smooth_state["yaw"]   = alpha * vel_cap(raw_yaw,   smooth_state["yaw"])   + (1-alpha) * smooth_state["yaw"]
            smooth_state["pitch"] = alpha * vel_cap(raw_pitch, smooth_state["pitch"]) + (1-alpha) * smooth_state["pitch"]
            smooth_state["eye"]   = alpha * vel_cap(raw_eye,   smooth_state["eye"])   + (1-alpha) * smooth_state["eye"]
            
            # Write to servos
            write_servo("neck_yaw",   smooth_state["yaw"])
            write_servo("neck_pitch", smooth_state["pitch"])
            write_servo("right_eye",  smooth_state["eye"])
            write_servo("left_eye",   smooth_state["eye"])
            
            # Draw overlay
            h, w = frame.shape[:2]
            cx = int(nose.x * w)
            cy = int(nose.y * h)
            cv2.circle(frame, (cx, cy), 8, (0, 255, 100), -1)
            cv2.rectangle(frame,
                (int(left_eye.x*w)-20, int(forehead.y*h)-20),
                (int(right_eye.x*w)+20, int(chin.y*h)+20),
                (0, 255, 100), 2
            )
        elif FACE_TRACKING_BACKEND == "opencv-haar":
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(80, 80)
            )
            if len(faces) > 0:
                x, y, fw, fh = max(faces, key=lambda item: item[2] * item[3])
                h, w = frame.shape[:2]
                cx = x + fw / 2
                cy = y + fh / 2
                yaw_ratio = clamp(cx / max(w, 1), 0.0, 1.0)
                pitch_ratio = clamp(cy / max(h, 1), 0.0, 1.0)

                raw_yaw = NECK_LEFT + (NECK_RIGHT - NECK_LEFT) * yaw_ratio
                raw_pitch = NECK_UP + (NECK_DOWN - NECK_UP) * pitch_ratio
                raw_eye = EYE_LEFT + (EYE_RIGHT - EYE_LEFT) * yaw_ratio

                smooth_state["yaw"] = alpha * vel_cap(raw_yaw, smooth_state["yaw"]) + (1-alpha) * smooth_state["yaw"]
                smooth_state["pitch"] = alpha * vel_cap(raw_pitch, smooth_state["pitch"]) + (1-alpha) * smooth_state["pitch"]
                smooth_state["eye"] = alpha * vel_cap(raw_eye, smooth_state["eye"]) + (1-alpha) * smooth_state["eye"]

                write_servo("neck_yaw", smooth_state["yaw"])
                write_servo("neck_pitch", smooth_state["pitch"])
                write_servo("right_eye", smooth_state["eye"])
                write_servo("left_eye", smooth_state["eye"])

                cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 180, 255), 2)
                cv2.circle(frame, (int(cx), int(cy)), 6, (0, 180, 255), -1)
        
        # Store latest frame
        with frame_lock:
            latest_faculty_frame = frame.copy()
        
        time.sleep(1/30)
    
    with camera_lock:
        if camera:
            camera.release()
            camera = None
    recalibrate_to_center()
    print("Face tracking stopped")

def start_tracking():
    global tracking_active, tracking_thread
    if tracking_active:
        return
    tracking_active = True
    tracking_thread = threading.Thread(
        target=tracking_loop, 
        daemon=True
    )
    tracking_thread.start()

def stop_tracking():
    global tracking_active, camera, tracking_thread
    tracking_active = False
    if tracking_thread and tracking_thread.is_alive():
        tracking_thread.join(timeout=2)
    with camera_lock:
        if camera:
            camera.release()
            camera = None
    tracking_thread = None

def get_faculty_frame_base64():
    import base64
    with frame_lock:
        if latest_faculty_frame is None:
            return None
        _, buffer = cv2.imencode(
            '.jpg', 
            latest_faculty_frame,
            [cv2.IMWRITE_JPEG_QUALITY, 75]
        )
        return base64.b64encode(buffer).decode('utf-8')

def is_face_tracking_available():
    return FACE_TRACKING_AVAILABLE

def get_face_tracking_backend():
    return FACE_TRACKING_BACKEND
