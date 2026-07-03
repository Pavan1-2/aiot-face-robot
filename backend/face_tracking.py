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

# ── State ─────────────────────────────────────────────────────────────────────
tracking_active = False
tracking_thread = None
camera          = None
latest_faculty_frame = None
frame_lock  = threading.Lock()
camera_lock = threading.Lock()

CAMERA_INDEX = int(os.getenv("FACULTY_CAMERA_INDEX", "0"))

# ── Spring-Damper Smoothing ───────────────────────────────────────────────────
#
# Instead of EMA (which breaks at low alpha due to int() rounding in write_servo),
# we use a spring-damper system:
#
#   velocity += STIFFNESS * (target - position)   ← spring pulls toward target
#   velocity *= DAMPING                            ← damper slows it down
#   position += velocity                           ← integrate
#
# Slider controls STIFFNESS:
#   Low  (0.05) → moves slowly and very smoothly  (overdamped)
#   High (0.90) → snaps to target instantly        (underdamped / responsive)
#
# DAMPING is fixed at 0.65 — prevents oscillation while still being fast.
# MAX_SPEED caps velocity so the servo never lurches more than N°/frame.
#
# Because we accumulate floating-point position and only write when the
# integer degree changes, sub-degree EMA movements are never lost.

_smooth_lock = threading.Lock()
_stiffness  = 0.30    # slider controls this: 0.05 (smooth) → 0.90 (snappy)
_damping    = 0.65    # fixed — prevents oscillation
_max_speed  = 12.0    # max degrees per frame (hard cap to stop lurching)

# Per-axis state: float positions + velocities
_pos = {"yaw": 90.0, "pitch": 90.0, "eye": 90.0}
_vel = {"yaw": 0.0,  "pitch": 0.0,  "eye": 0.0}

# Track last written integer angle to avoid redundant hardware writes
_last_written = {"neck_yaw": -1, "neck_pitch": -1, "right_eye": -1, "left_eye": -1}

# ── Servo Output Range ────────────────────────────────────────────────────────
#
# Maximum physical travel of each servo.
# These are WIDER than before to guarantee full visible movement.
#
# Yaw  (left/right) : 20° … 160°  = 140° total sweep
# Pitch (up/down)   : 30° … 150°  = 120° total sweep
# Eyes (horizontal) : 45° … 135°  =  90° total sweep

NECK_LEFT  = 20;  NECK_RIGHT = 160   # yaw:   widest possible
NECK_UP    = 30;  NECK_DOWN  = 150   # pitch: widest possible
EYE_LEFT   = 45;  EYE_RIGHT  = 135   # eyes

# ── Face Ratio Input Band ─────────────────────────────────────────────────────
#
# Narrow band = small head movement → large servo sweep.
# Wider band  = you have to turn your head a lot to get full servo range.
#
# Tighter than before to amplify small movements:
YAW_IN_MIN   = 0.28;  YAW_IN_MAX   = 0.72   # was 0.20–0.80
PITCH_IN_MIN = 0.38;  PITCH_IN_MAX = 0.62   # was 0.35–0.65

# ── Helpers ───────────────────────────────────────────────────────────────────

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def map_range(val, in_min, in_max, out_min, out_max):
    return clamp(
        (val - in_min) * (out_max - out_min) /
        (in_max - in_min + 1e-6) + out_min,
        min(out_min, out_max),
        max(out_min, out_max)
    )

def _spring_step(axis: str, target: float) -> float:
    """
    Advance one frame of spring-damper physics for the given axis.
    Returns new float position.
    Thread-safe read of smoothing params.
    """
    with _smooth_lock:
        k    = _stiffness
        d    = _damping
        vmax = _max_speed

    # Spring force pulls position toward target
    error = target - _pos[axis]
    _vel[axis] += k * error
    # Damping
    _vel[axis] *= d
    # Hard speed cap
    _vel[axis] = clamp(_vel[axis], -vmax, vmax)
    # Integrate
    _pos[axis] += _vel[axis]
    return _pos[axis]

def _write_if_changed(servo_name: str, float_angle: float):
    """
    Write to hardware only when the integer angle actually changes.
    This avoids the issue where sub-degree EMA changes are lost to int().
    """
    new_int = int(round(float_angle))
    if new_int != _last_written.get(servo_name, -1):
        _last_written[servo_name] = new_int
        write_servo(servo_name, float_angle)

# ── Public Smoothing API ───────────────────────────────────────────────────────

def set_smoothness(value: float):
    """
    Set stiffness from slider.
    value = 0.0 (max smooth) → 1.0 (max responsive) — maps to stiffness 0.05–0.90.
    Can also be called directly with a raw stiffness value.
    """
    global _stiffness
    # Accept either normalised 0-1 or raw stiffness (both < 1.0 so same)
    stiffness = clamp(float(value), 0.03, 0.95)
    with _smooth_lock:
        _stiffness = stiffness
    print(f"Tracking stiffness={_stiffness:.3f}")

def get_smoothness() -> float:
    with _smooth_lock:
        return _stiffness

def get_tracking_params() -> dict:
    with _smooth_lock:
        return {
            "alpha":     _stiffness,   # named 'alpha' for API compat
            "stiffness": _stiffness,
            "damping":   _damping,
            "max_speed": _max_speed,
            "yaw_range":   [NECK_LEFT, NECK_RIGHT],
            "pitch_range": [NECK_UP,   NECK_DOWN],
        }

# ── Tracking Loop ─────────────────────────────────────────────────────────────

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
            rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

        if results and results.multi_face_landmarks:
            lm = results.multi_face_landmarks[0].landmark

            nose      = lm[1]
            left_eye  = lm[33]
            right_eye = lm[263]
            forehead  = lm[10]
            chin      = lm[152]

            # ── Yaw ratio (left/right) ──────────────────────────────────────
            eye_width = right_eye.x - left_eye.x
            if eye_width > 1e-4:
                yaw_ratio = map_range(
                    (nose.x - left_eye.x) / eye_width,
                    YAW_IN_MIN, YAW_IN_MAX, 0.0, 1.0
                )
            else:
                yaw_ratio = 0.5

            # ── Pitch ratio (up/down) ───────────────────────────────────────
            face_height = chin.y - forehead.y
            if face_height > 1e-4:
                pitch_ratio = map_range(
                    (nose.y - forehead.y) / face_height,
                    PITCH_IN_MIN, PITCH_IN_MAX, 0.0, 1.0
                )
            else:
                pitch_ratio = 0.5

            # ── Raw servo targets ───────────────────────────────────────────
            tgt_yaw   = NECK_LEFT  + (NECK_RIGHT - NECK_LEFT)  * yaw_ratio
            tgt_pitch = NECK_UP    + (NECK_DOWN  - NECK_UP)    * pitch_ratio
            tgt_eye   = EYE_LEFT   + (EYE_RIGHT  - EYE_LEFT)   * yaw_ratio

            # ── Spring-damper step ──────────────────────────────────────────
            yaw_pos   = _spring_step("yaw",   tgt_yaw)
            pitch_pos = _spring_step("pitch", tgt_pitch)
            eye_pos   = _spring_step("eye",   tgt_eye)

            # ── Write (only when integer angle actually changes) ─────────────
            _write_if_changed("neck_yaw",   yaw_pos)
            _write_if_changed("neck_pitch", pitch_pos)
            _write_if_changed("right_eye",  eye_pos)
            _write_if_changed("left_eye",   eye_pos)

            # ── Overlay ────────────────────────────────────────────────────
            h, w = frame.shape[:2]
            cx = int(nose.x * w)
            cy = int(nose.y * h)
            cv2.circle(frame, (cx, cy), 8, (0, 255, 100), -1)
            cv2.rectangle(frame,
                (int(left_eye.x * w) - 20, int(forehead.y * h) - 20),
                (int(right_eye.x * w) + 20, int(chin.y * h) + 20),
                (0, 255, 100), 2
            )
            with _smooth_lock:
                k = _stiffness
            label = f"stiffness={k:.2f}  yaw={yaw_pos:.1f}  pitch={pitch_pos:.1f}"
            cv2.putText(frame, label, (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 100), 2)

        elif FACE_TRACKING_BACKEND == "opencv-haar":
            gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
            )
            if len(faces) > 0:
                x, y, fw, fh = max(faces, key=lambda item: item[2] * item[3])
                h, w = frame.shape[:2]
                cx = x + fw / 2
                cy = y + fh / 2
                yaw_ratio   = clamp(cx / max(w, 1), 0.0, 1.0)
                pitch_ratio = clamp(cy / max(h, 1), 0.0, 1.0)

                tgt_yaw   = NECK_LEFT + (NECK_RIGHT - NECK_LEFT) * yaw_ratio
                tgt_pitch = NECK_UP   + (NECK_DOWN  - NECK_UP)   * pitch_ratio
                tgt_eye   = EYE_LEFT  + (EYE_RIGHT  - EYE_LEFT)  * yaw_ratio

                yaw_pos   = _spring_step("yaw",   tgt_yaw)
                pitch_pos = _spring_step("pitch", tgt_pitch)
                eye_pos   = _spring_step("eye",   tgt_eye)

                _write_if_changed("neck_yaw",   yaw_pos)
                _write_if_changed("neck_pitch", pitch_pos)
                _write_if_changed("right_eye",  eye_pos)
                _write_if_changed("left_eye",   eye_pos)

                cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 180, 255), 2)
                cv2.circle(frame, (int(cx), int(cy)), 6, (0, 180, 255), -1)

        # Store latest frame
        with frame_lock:
            latest_faculty_frame = frame.copy()

        time.sleep(1 / 30)

    with camera_lock:
        if camera:
            camera.release()
            camera = None
    recalibrate_to_center()
    print("Face tracking stopped")

# ── Thread Control ─────────────────────────────────────────────────────────────

def start_tracking():
    global tracking_active, tracking_thread, _pos, _vel, _last_written
    if tracking_active:
        return
    # Reset spring state so it starts from center
    _pos.update({"yaw": 90.0, "pitch": 90.0, "eye": 90.0})
    _vel.update({"yaw": 0.0,  "pitch": 0.0,  "eye": 0.0})
    _last_written.update({"neck_yaw": -1, "neck_pitch": -1, "right_eye": -1, "left_eye": -1})
    tracking_active = True
    tracking_thread = threading.Thread(target=tracking_loop, daemon=True)
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
