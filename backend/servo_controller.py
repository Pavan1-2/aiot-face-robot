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

# Servo channel mapping
SERVO_MAP = {
    "right_eye": 0,
    "left_eye": 1,
    "eyelid": 2,
    "neck_pitch": 3,
    "neck_yaw": 4
}

# Mechanical limits
LIMITS = {
    "right_eye":  {"min": 40,  "max": 140, "center": 90},
    "left_eye":   {"min": 40,  "max": 140, "center": 90},
    "eyelid":     {"min": 0,   "max": 110, "center": 90},
    "neck_pitch": {"min": 35,  "max": 145, "center": 90},
    "neck_yaw":   {"min": 30,  "max": 150, "center": 90}
}

# Current state
current_state = {
    "neck_pitch": 90,
    "neck_yaw": 90,
    "right_eye": 90,
    "left_eye": 90,
    "eyelid": 90
}

def clamp(val, lo, hi):
    return max(lo, min(hi, val))

def write_servo(servo_name, angle):
    global current_state
    if servo_name not in LIMITS:
        print(f"Unknown servo: {servo_name}")
        return

    limit = LIMITS[servo_name]
    safe_angle = clamp(angle, limit["min"], limit["max"])

    if not HARDWARE_AVAILABLE:
        current_state[servo_name] = safe_angle
        return
    
    channel = SERVO_MAP[servo_name]
    
    try:
        kit.servo[channel].angle = int(safe_angle)
        current_state[servo_name] = safe_angle
    except Exception as e:
        print(f"Servo write error: {e}")

def recalibrate_to_center():
    for servo_name, limits in LIMITS.items():
        write_servo(servo_name, limits["center"])
    print("All servos centered")

def emergency_stop():
    if HARDWARE_AVAILABLE and kit:
        try:
            for i in range(16):
                kit.servo[i].angle = None
        except:
            pass
    print("EMERGENCY STOP TRIGGERED")

def get_current_state():
    return current_state.copy()

def blink():
    write_servo("eyelid", 0)
    import time
    time.sleep(0.15)
    write_servo("eyelid", 110)
