# backend/servo_controller.py

try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16)
    HARDWARE_AVAILABLE = True
    print("PCA9685 servo driver connected")
except Exception as e:
    print(f"Servo driver not found: {e} - Running in simulation mode")
    HARDWARE_AVAILABLE = False
    kit = None

# ─── Robot Configuration ───────────────────────────────────────────────────────
#
# Three robots share one PCA9685 (16 channels, indexed 0-15).
# Channel mapping:
#   Robot 1 → channels 1-5
#   Robot 2 → channels 6-10
#   Robot 3 → channels 11-15
#
# Servo order within each robot (offset from robot base channel):
#   0: right_eye
#   1: left_eye
#   2: eyelid
#   3: neck_pitch
#   4: neck_yaw

SERVO_NAMES = ["right_eye", "left_eye", "eyelid", "neck_pitch", "neck_yaw"]

ROBOT_BASE_CHANNELS = {
    1: 1,   # Robot 1: channels 1-5
    2: 6,   # Robot 2: channels 6-10
    3: 11,  # Robot 3: channels 11-15
}

def _channel(robot_id: int, servo_name: str) -> int:
    """Return the PCA9685 channel for a given robot and servo."""
    offset = SERVO_NAMES.index(servo_name)
    return ROBOT_BASE_CHANNELS[robot_id] + offset

# Mechanical limits (same for all 3 robots)
# These must be >= the output range used in face_tracking.py
LIMITS = {
    "right_eye":  {"min": 40,  "max": 140, "center": 90},
    "left_eye":   {"min": 40,  "max": 140, "center": 90},
    "eyelid":     {"min": 0,   "max": 110, "center": 90},
    "neck_pitch": {"min": 30,  "max": 150, "center": 90},   # widened from 35/145
    "neck_yaw":   {"min": 20,  "max": 160, "center": 90},   # widened from 30/150
}

# Per-robot enable flags (all enabled by default)
_enabled_robots: set[int] = {1, 2, 3}

# Per-robot current servo angles
_current_state: dict[int, dict[str, float]] = {
    r: {name: 90.0 for name in SERVO_NAMES}
    for r in ROBOT_BASE_CHANNELS
}

# ─── Helpers ───────────────────────────────────────────────────────────────────

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

# ─── Public API ────────────────────────────────────────────────────────────────

def set_robot_enabled(robot_id: int, enabled: bool):
    """Enable or disable a robot. Disabled robots ignore write_servo calls."""
    if robot_id not in ROBOT_BASE_CHANNELS:
        print(f"Unknown robot id: {robot_id}")
        return
    if enabled:
        _enabled_robots.add(robot_id)
        print(f"Robot {robot_id} ENABLED")
    else:
        _enabled_robots.discard(robot_id)
        print(f"Robot {robot_id} DISABLED")

def get_enabled_robots() -> list[int]:
    return sorted(_enabled_robots)

def write_servo(servo_name: str, angle: float, robot_ids=None):
    """
    Write an angle to the named servo on all enabled robots (or a subset).

    Args:
        servo_name: One of SERVO_NAMES.
        angle:      Target angle (will be clamped to LIMITS).
        robot_ids:  Optional list/set of robot IDs to target.
                    Defaults to all currently enabled robots.
    """
    if servo_name not in LIMITS:
        print(f"Unknown servo: {servo_name}")
        return

    limit = LIMITS[servo_name]
    safe_angle = clamp(angle, limit["min"], limit["max"])

    targets = _enabled_robots if robot_ids is None else (set(robot_ids) & _enabled_robots)

    for robot_id in targets:
        _current_state[robot_id][servo_name] = safe_angle

        if not HARDWARE_AVAILABLE:
            continue

        ch = _channel(robot_id, servo_name)
        try:
            kit.servo[ch].angle = int(safe_angle)
        except Exception as e:
            print(f"Servo write error (robot {robot_id}, ch {ch}): {e}")

def recalibrate_to_center(robot_ids=None):
    """Center all servos on the specified robots (default: all enabled)."""
    for servo_name, limits in LIMITS.items():
        write_servo(servo_name, limits["center"], robot_ids=robot_ids)
    targets = sorted(robot_ids or _enabled_robots)
    print(f"Robots {targets}: all servos centered")

def emergency_stop():
    """Cut PWM signal to every channel on the board."""
    if HARDWARE_AVAILABLE and kit:
        try:
            for i in range(16):
                kit.servo[i].angle = None
        except Exception:
            pass
    # Clear simulated state for all robots
    for robot_id in _current_state:
        for name in SERVO_NAMES:
            _current_state[robot_id][name] = 90.0
    print("EMERGENCY STOP TRIGGERED")

def get_current_state() -> dict:
    """
    Return a flat dict of servo angles for backward-compatible `/api/status`.
    Uses the first enabled robot's values (or Robot 1 as fallback).
    """
    ref = min(_enabled_robots) if _enabled_robots else 1
    return _current_state[ref].copy()

def get_all_robot_states() -> dict:
    """Return full per-robot state dict: {robot_id: {servo_name: angle}}."""
    return {
        r: state.copy()
        for r, state in _current_state.items()
    }

def get_robot_enabled_state() -> dict:
    """Return {robot_id: bool} for all robots."""
    return {r: (r in _enabled_robots) for r in ROBOT_BASE_CHANNELS}

def blink(robot_ids=None):
    """Quick eyelid blink on the specified robots (default: all enabled)."""
    import time
    write_servo("eyelid", 0, robot_ids=robot_ids)
    time.sleep(0.15)
    write_servo("eyelid", 110, robot_ids=robot_ids)
