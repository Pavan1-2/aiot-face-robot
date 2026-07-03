import { useEffect, useMemo, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_BASE = API_BASE.replace(/^http/, 'ws')

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

export default function App() {
  const [status, setStatus] = useState(null)
  const [question, setQuestion] = useState('')
  const [useCamera, setUseCamera] = useState(false)
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const classroomImage = useImageSocket('/ws/classroom-feed')
  const facultyImage = useImageSocket('/ws/faculty-feed')
  const vinuImage = useImageSocket('/ws/vinu-feed')

  const servoEntries = useMemo(() => {
    if (!status?.servos) return []
    return Object.entries(status.servos)
  }, [status])

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

      <section className="controlGrid">
        <div className="panel">
          <h2>Mode</h2>
          <div className="buttonRow">
            <button disabled={busy} onClick={() => post('/api/mode/tracking')}>Tracking</button>
            <button disabled={busy} onClick={() => post('/api/mode/vinu')}>VINU</button>
            <button disabled={busy} onClick={() => post('/api/mode/idle')}>Idle</button>
          </div>
        </div>

        <div className="panel">
          <h2>Servo</h2>
          <div className="buttonRow">
            <button disabled={busy} onClick={() => post('/api/servo/center')}>Center</button>
            <button disabled={busy} onClick={() => post('/api/servo/blink')}>Blink</button>
            <button className="danger" disabled={busy} onClick={() => post('/api/servo/estop')}>E-Stop</button>
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

      <section className="feeds">
        <Feed title="Classroom Feed" image={classroomImage} emptyText="Waiting for Raspberry Pi stream" />
        <Feed title="Faculty Feed" image={facultyImage} emptyText="Start tracking mode to view camera" />
        <Feed title="VINU Camera" image={vinuImage} emptyText="Start VINU mode to view camera" />
      </section>

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
            <button disabled={busy || !question.trim()} type="submit">Ask</button>
            <button disabled={busy} type="button" onClick={() => post('/api/vinu/clear')}>Clear History</button>
          </div>
          {reply && <p className="reply">{reply}</p>}
        </form>

        <section className="panel">
          <h2>Servo Angles</h2>
          <div className="servoList">
            {servoEntries.map(([name, value]) => (
              <div className="servoRow" key={name}>
                <span>{name.replace('_', ' ')}</span>
                <meter min="0" max="180" value={Number(value)} />
                <strong>{Math.round(Number(value))} deg</strong>
              </div>
            ))}
          </div>
        </section>
      </section>
    </main>
  )
}
