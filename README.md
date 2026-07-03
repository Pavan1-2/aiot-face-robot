# AIoT Face Robot

FastAPI + React control dashboard for an AIoT face robot. The backend controls servo simulation/hardware, face tracking, Raspberry Pi video streaming, audio passthrough, and the VINU teaching assistant.

## Project Layout

- `backend/` - FastAPI API, WebSockets, tracking, VINU, servo control
- `frontend/` - Vite React dashboard
- `rp/` - Raspberry Pi ZeroMQ camera stream publisher
- `requirements.txt` - Python dependencies
- `.env.example` - runtime configuration template

## Backend Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

For the physical robot with audio passthrough and PCA9685 servo hardware, install the optional hardware dependencies:

```powershell
pip install -r requirements-hardware.txt
```

Edit `.env` and set:

```text
GROQ_API_KEY=your_groq_api_key
PI_STREAM_HOST=your_raspberry_pi_ip
```

Start the API:

```powershell
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will run in simulation mode if the PCA9685 servo driver is not connected. Audio passthrough is disabled automatically when PyAudio is unavailable.

## Frontend Setup

```powershell
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:3000
```

If the backend is on another host, create `frontend/.env`:

```text
VITE_API_BASE_URL=http://backend-host:8000
```

## Raspberry Pi Stream

On the Raspberry Pi:

```bash
pip install opencv-python pyzmq
python rp/stream_server.py
```

For Pi camera support, install `picamera2` through the Raspberry Pi OS package manager. Configure the receiver host in the backend `.env`:

```text
PI_STREAM_HOST=raspberry-pi-ip
PI_STREAM_PORT=5555
```

## Useful API Routes

- `GET /api/status`
- `POST /api/mode/tracking`
- `POST /api/mode/vinu`
- `POST /api/mode/idle`
- `POST /api/servo/center`
- `POST /api/servo/blink`
- `POST /api/servo/estop`
- `POST /api/vinu/query`
- `POST /api/vinu/clear`

## WebSockets

- `/ws/classroom-feed`
- `/ws/faculty-feed`
- `/ws/vinu-feed`
- `/ws/servo-status`
