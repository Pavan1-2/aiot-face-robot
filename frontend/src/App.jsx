import { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useImageSocket(path) {
  const [image, setImage] = useState('')

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}${path}`)
    socket.onmessage = (event) => {
      setImage(`data:image/jpeg;base64,${event.data}`)
    }
    socket.onerror = () => {
      socket.close()
    }
    return () => socket.close()
  }, [path])

  return image
}

// ─── Components ───────────────────────────────────────────────────────────────

function Feed({ title, image, emptyText }) {
  return (
    <section className="feed">
      <div className="feedHeader">
        <h2>{title}</h2>
      </div>
      <div className="videoFrame">
        {image ? <img src={image} alt={title} /> : <span>{emptyText}</span>}
      </div>
    </section>
  )
}

/** Toggle switch for enabling/disabling a single robot */
function RobotToggle({ robotId, enabled, busy, onToggle }) {
  return (
    <div className="robotToggle">
      <span className="robotLabel">Robot {robotId}</span>
      <label className={`toggleSwitch ${busy ? 'toggleDisabled' : ''}`} title={`Toggle Robot ${robotId}`}>
        <input
          id={`robot-toggle-${robotId}`}
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={() => onToggle(robotId, !enabled)}
        />
        <span className="toggleTrack">
          <span className="toggleThumb" />
        </span>
      </label>
      <span className={`robotStatus ${enabled ? 'on' : 'off'}`}>
        {enabled ? 'ON' : 'OFF'}
      </span>
    </div>
  )
}

/** Grouped servo angle display for one robot */
function RobotServoGroup({ robotId, servos, enabled }) {
  return (
    <div className={`robotServoGroup ${enabled ? '' : 'robotDisabled'}`}>
      <div className="robotServoHeader">
        <span className="robotGroupLabel">Robot {robotId}</span>
        {!enabled && <span className="disabledChip">disabled</span>}
      </div>
      {Object.entries(servos).map(([name, value]) => (
        <div className="servoRow" key={name}>
          <span>{name.replace(/_/g, ' ')}</span>
          <meter min="0" max="180" value={Number(value)} />
          <strong>{Math.round(Number(value))} °</strong>
        </div>
      ))}
    </div>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [status, setStatus] = useState(null)
  const [question, setQuestion] = useState('')
  const [useCamera, setUseCamera] = useState(false)
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const classroomImage = useImageSocket('/ws/classroom-feed')
  const facultyImage   = useImageSocket('/ws/faculty-feed')
  const vinuImage      = useImageSocket('/ws/vinu-feed')

  // Robots: {1: true, 2: true, 3: true} — parse keys as numbers
  const robotsEnabled = useMemo(() => {
    if (!status?.robots) return { 1: true, 2: true, 3: true }
    return Object.fromEntries(
      Object.entries(status.robots).map(([k, v]) => [Number(k), v])
    )
  }, [status])

  const robotServos = useMemo(() => {
    if (!status?.robot_servos) return {}
    return Object.fromEntries(
      Object.entries(status.robot_servos).map(([k, v]) => [Number(k), v])
    )
  }, [status])

  // ── API helpers ──────────────────────────────────────────────────────────

  async function refreshStatus() {
    try {
      const { data } = await axios.get(`${API_BASE}/api/status`)
      setStatus(data)
      setError('')
    } catch {
      setError('Backend is not reachable')
    }
  }

  async function post(path) {
    setBusy(true)
    try {
      await axios.post(`${API_BASE}${path}`)
      await refreshStatus()
    } catch {
      setError(`Request failed: ${path}`)
    } finally {
      setBusy(false)
    }
  }

  async function toggleRobot(robotId, enable) {
    setBusy(true)
    const action = enable ? 'enable' : 'disable'
    try {
      await axios.post(`${API_BASE}/api/robots/${robotId}/${action}`)
      await refreshStatus()
    } catch {
      setError(`Failed to ${action} Robot ${robotId}`)
    } finally {
      setBusy(false)
    }
  }

  async function askVinu(event) {
    event.preventDefault()
    if (!question.trim()) return
    setBusy(true)
    setReply('')
    try {
      const { data } = await axios.post(`${API_BASE}/api/vinu/query`, {
        text: question,
        use_camera: useCamera,
      })
      setReply(data.response)
      await refreshStatus()
    } catch {
      setError('VINU query failed')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    refreshStatus()
    const id = window.setInterval(refreshStatus, 2000)
    return () => window.clearInterval(id)
  }, [])

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>AIoT Face Robot</h1>
          <p>Robot control, classroom stream, face tracking, and VINU assistant.</p>
        </div>
        <div className={`modeBadge ${status?.mode || 'offline'}`}>
          {status?.mode || 'offline'}
        </div>
      </header>

      {error && <div className="alert">{error}</div>}

      {/* ── Row 1: Mode / Servo / Status ── */}
      <section className="controlGrid">
        <div className="panel">
          <h2>Mode</h2>
          <div className="buttonRow">
            <button id="btn-mode-tracking" disabled={busy} onClick={() => post('/api/mode/tracking')}>Tracking</button>
            <button id="btn-mode-vinu"     disabled={busy} onClick={() => post('/api/mode/vinu')}>VINU</button>
            <button id="btn-mode-idle"     disabled={busy} onClick={() => post('/api/mode/idle')}>Idle</button>
          </div>
        </div>

        <div className="panel">
          <h2>Servo</h2>
          <div className="buttonRow">
            <button id="btn-servo-center" disabled={busy} onClick={() => post('/api/servo/center')}>Center</button>
            <button id="btn-servo-blink"  disabled={busy} onClick={() => post('/api/servo/blink')}>Blink</button>
            <button id="btn-servo-estop"  className="danger" disabled={busy} onClick={() => post('/api/servo/estop')}>E-Stop</button>
          </div>
        </div>

        <div className="panel statusPanel">
          <h2>Status</h2>
          <dl>
            <dt>Pi stream</dt>
            <dd>{status?.pi_connected ? 'connected' : 'waiting'}</dd>
            <dt>VINU</dt>
            <dd>{status?.vinu_configured ? status.vinu_status : 'needs API key'}</dd>
            <dt>Audio</dt>
            <dd>{status?.audio_available ? 'available' : 'disabled'}</dd>
            <dt>Face mesh</dt>
            <dd>{status?.face_tracking_available ? status.face_tracking_backend : 'feed only'}</dd>
          </dl>
        </div>
      </section>

      {/* ── Row 2: Robot Toggles ── */}
      <section className="panel robotPanel">
        <h2>Robots</h2>
        <div className="robotTogglesRow">
          {[1, 2, 3].map((id) => (
            <RobotToggle
              key={id}
              robotId={id}
              enabled={robotsEnabled[id] ?? true}
              busy={busy}
              onToggle={toggleRobot}
            />
          ))}
        </div>
        <p className="robotHint">
          All enabled robots mirror the same movements.
          Disabled robots hold their current position.
        </p>
      </section>

      {/* ── Row 3: Video Feeds ── */}
      <section className="feeds">
        <Feed title="Classroom Feed" image={classroomImage} emptyText="Waiting for Raspberry Pi stream" />
        <Feed title="Faculty Feed"   image={facultyImage}   emptyText="Start tracking mode to view camera" />
        <Feed title="VINU Camera"    image={vinuImage}      emptyText="Start VINU mode to view camera" />
      </section>

      {/* ── Row 4: VINU + Servo Angles ── */}
      <section className="bottomGrid">
        <form className="panel vinuPanel" onSubmit={askVinu}>
          <h2>VINU Query</h2>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask VINU a teaching or object-identification question"
          />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={useCamera}
              onChange={(event) => setUseCamera(event.target.checked)}
            />
            Use VINU camera frame
          </label>
          <div className="buttonRow">
            <button id="btn-vinu-ask"   disabled={busy || !question.trim()} type="submit">Ask</button>
            <button id="btn-vinu-clear" disabled={busy} type="button" onClick={() => post('/api/vinu/clear')}>Clear History</button>
          </div>
          {reply && <p className="reply">{reply}</p>}
        </form>

        <section className="panel">
          <h2>Servo Angles</h2>
          <div className="servoList">
            {[1, 2, 3].map((id) => (
              <RobotServoGroup
                key={id}
                robotId={id}
                servos={robotServos[id] ?? {}}
                enabled={robotsEnabled[id] ?? true}
              />
            ))}
          </div>
        </section>
      </section>
    </main>
  )
}
