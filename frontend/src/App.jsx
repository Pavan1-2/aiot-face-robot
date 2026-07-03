import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const WS_BASE  = API_BASE.replace(/^http/, 'ws')

// ─── Debounce ─────────────────────────────────────────────────────────────────
function useDebounce(fn, delay) {
  const timer = useRef(null)
  return useCallback((...args) => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => fn(...args), delay)
  }, [fn, delay])
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useImageSocket(path) {
  const [image, setImage] = useState('')
  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}${path}`)
    socket.onmessage = (e) => setImage(`data:image/jpeg;base64,${e.data}`)
    socket.onerror   = ()  => socket.close()
    return () => socket.close()
  }, [path])
  return image
}

// ─── Small Components ─────────────────────────────────────────────────────────

function Feed({ title, image, emptyText }) {
  return (
    <section className="feed">
      <div className="feedHeader"><h2>{title}</h2></div>
      <div className="videoFrame">
        {image ? <img src={image} alt={title} /> : <span>{emptyText}</span>}
      </div>
    </section>
  )
}

function RobotToggle({ robotId, enabled, busy, onToggle }) {
  return (
    <div className="robotToggle">
      <span className="robotLabel">Robot {robotId}</span>
      <label className={`toggleSwitch ${busy ? 'toggleDisabled' : ''}`}>
        <input
          id={`robot-toggle-${robotId}`}
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={() => onToggle(robotId, !enabled)}
        />
        <span className="toggleTrack"><span className="toggleThumb" /></span>
      </label>
      <span className={`robotStatus ${enabled ? 'on' : 'off'}`}>
        {enabled ? 'ON' : 'OFF'}
      </span>
    </div>
  )
}

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

// ─── Voice State Badge ────────────────────────────────────────────────────────

const VOICE_LABELS = {
  idle:          'Idle',
  recording:     '● Recording…',
  transcribing:  '⟳ Transcribing…',
  thinking:      '⟳ Thinking…',
  speaking:      '▶ Speaking…',
}
const VOICE_COLORS = {
  idle:         'voiceIdle',
  recording:    'voiceRecording',
  transcribing: 'voiceBusy',
  thinking:     'voiceBusy',
  speaking:     'voiceSpeaking',
}

function VoiceBadge({ state }) {
  return (
    <span className={`voiceBadge ${VOICE_COLORS[state] || 'voiceIdle'}`}>
      {VOICE_LABELS[state] || state}
    </span>
  )
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [status,    setStatus]    = useState(null)
  const [question,  setQuestion]  = useState('')
  const [useCamera, setUseCamera] = useState(false)
  const [reply,     setReply]     = useState('')
  const [busy,      setBusy]      = useState(false)
  const [error,     setError]     = useState('')

  // Audio passthrough
  const [audioActive, setAudioActive] = useState(false)
  const [audioBusy,   setAudioBusy]   = useState(false)

  // Smoothness
  const [smoothness,      setSmoothness]      = useState(0.10)
  const [smoothnessBusy,  setSmoothnessbusy]  = useState(false)

  // Voice chat
  const [voiceState,      setVoiceState]      = useState('idle')
  const [voiceTranscript, setVoiceTranscript] = useState('')
  const [voiceReply,      setVoiceReply]      = useState('')
  const voiceWsRef   = useRef(null)
  const mediaRecRef  = useRef(null)
  const isRecording  = voiceState === 'recording'

  const classroomImage = useImageSocket('/ws/classroom-feed')
  const facultyImage   = useImageSocket('/ws/faculty-feed')
  const vinuImage      = useImageSocket('/ws/vinu-feed')

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
      setAudioActive(data.audio_active ?? false)
      setVoiceState(data.voice_state ?? 'idle')
      setError('')
    } catch {
      setError('Backend is not reachable')
    }
  }

  async function loadTrackingParams() {
    try {
      const { data } = await axios.get(`${API_BASE}/api/tracking/params`)
      setSmoothness(data.alpha)
    } catch {}
  }

  const sendSmoothness = useCallback(async (alpha) => {
    setSmoothnessbusy(true)
    try {
      await axios.patch(`${API_BASE}/api/tracking/smoothness`, { alpha })
    } catch {
      setError('Failed to update smoothness')
    } finally {
      setSmoothnessbusy(false)
    }
  }, [])

  const debouncedSendSmoothness = useDebounce(sendSmoothness, 300)

  function handleSmoothnessChange(e) {
    const val = parseFloat(e.target.value)
    setSmoothness(val)
    debouncedSendSmoothness(val)
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
    try {
      await axios.post(`${API_BASE}/api/robots/${robotId}/${enable ? 'enable' : 'disable'}`)
      await refreshStatus()
    } catch {
      setError(`Failed to ${enable ? 'enable' : 'disable'} Robot ${robotId}`)
    } finally {
      setBusy(false)
    }
  }

  async function toggleAudio() {
    setAudioBusy(true)
    try {
      const path = audioActive ? '/api/audio/passthrough/off' : '/api/audio/passthrough/on'
      const { data } = await axios.post(`${API_BASE}${path}`)
      setAudioActive(data.active)
    } catch {
      setError('Failed to toggle audio passthrough')
    } finally {
      setAudioBusy(false)
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

  // ── Voice Chat ───────────────────────────────────────────────────────────

  const openVoiceSocket = useCallback(() => {
    if (voiceWsRef.current) return voiceWsRef.current
    const ws = new WebSocket(`${WS_BASE}/ws/voice-chat`)
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.state)      setVoiceState(msg.state)
        if (msg.transcript) setVoiceTranscript(msg.transcript)
        if (msg.reply) {
          setVoiceReply(msg.reply)
          setReply(msg.reply)   // also show in main VINU reply area
        }
        if (msg.transcript)  setQuestion(msg.transcript)
      } catch {}
    }
    ws.onerror = () => { setError('Voice chat connection error'); ws.close() }
    ws.onclose = () => { voiceWsRef.current = null; setVoiceState('idle') }
    voiceWsRef.current = ws
    return ws
  }, [])

  async function startVoiceRecording() {
    setVoiceTranscript('')
    setVoiceReply('')

    const ws = openVoiceSocket()
    // Wait for socket to open
    await new Promise((resolve) => {
      if (ws.readyState === WebSocket.OPEN) return resolve()
      ws.addEventListener('open', resolve, { once: true })
    })

    // Request mic permission and start MediaRecorder
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
    } catch {
      setError('Microphone permission denied')
      return
    }

    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
    mediaRecRef.current = recorder

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
        ws.send(e.data)
      }
    }

    recorder.start(250) // send chunks every 250 ms
    ws.send('START')
    setVoiceState('recording')
  }

  async function stopVoiceRecording() {
    const recorder = mediaRecRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
      recorder.stream.getTracks().forEach((t) => t.stop())
      mediaRecRef.current = null
    }
    const ws = voiceWsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('STOP')
    }
    setVoiceState('transcribing')
  }

  function handleVoiceButton() {
    if (isRecording) {
      stopVoiceRecording()
    } else {
      startVoiceRecording()
    }
  }

  // cleanup on unmount
  useEffect(() => {
    return () => {
      voiceWsRef.current?.close()
      mediaRecRef.current?.stop()
    }
  }, [])

  useEffect(() => {
    refreshStatus()
    loadTrackingParams()
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
          <div className="smoothnessRow">
            <label className="smoothnessLabel" htmlFor="smoothness-slider">
              Smoothness
            </label>
            <input
              id="smoothness-slider"
              type="range"
              min="0.01"
              max="0.50"
              step="0.01"
              value={smoothness}
              onChange={handleSmoothnessChange}
              disabled={smoothnessBusy}
              className="smoothnessSlider"
            />
            <span className="smoothnessValue">
              {smoothness <= 0.08 ? '🐢 Max Smooth' :
               smoothness >= 0.40 ? '⚡ Responsive' :
               `${Math.round((1 - smoothness / 0.5) * 100)}%`}
            </span>
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
            <dd>{status?.audio_available ? (status.audio_active ? 'passthrough on' : 'available') : 'disabled'}</dd>
            <dt>Face mesh</dt>
            <dd>{status?.face_tracking_available ? status.face_tracking_backend : 'feed only'}</dd>
          </dl>
        </div>
      </section>

      {/* ── Row 2: Robots + Audio ── */}
      <section className="hardwareRow">
        {/* Robot Toggles */}
        <div className="panel robotPanel">
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
          <p className="robotHint">All enabled robots mirror the same movements.</p>
        </div>

        {/* Audio Passthrough */}
        <div className="panel audioPanel">
          <h2>Audio Passthrough</h2>
          <div className="audioToggleRow">
            <div className={`audioCard ${audioActive ? 'audioCardOn' : ''}`}>
              <div className="audioCardInfo">
                <span className="audioCardTitle">USB Mic → Speaker</span>
                <span className="audioCardSub">
                  {status?.audio_available
                    ? (audioActive ? 'Passthrough active' : 'Ready')
                    : 'PyAudio not installed'}
                </span>
              </div>
              <label className={`toggleSwitch ${audioBusy || !status?.audio_available ? 'toggleDisabled' : ''}`}>
                <input
                  id="audio-passthrough-toggle"
                  type="checkbox"
                  checked={audioActive}
                  disabled={audioBusy || !status?.audio_available}
                  onChange={toggleAudio}
                />
                <span className="toggleTrack"><span className="toggleThumb" /></span>
              </label>
              <span className={`robotStatus ${audioActive ? 'on' : 'off'}`}>
                {audioActive ? 'ON' : 'OFF'}
              </span>
            </div>
          </div>
          <p className="robotHint">Real-time mic → MAX9744 amp → speaker passthrough.</p>
        </div>
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

          {/* ─ Voice Chat ─ */}
          <div className="voiceChatBar">
            <button
              id="btn-voice-chat"
              type="button"
              className={`voiceBtn ${isRecording ? 'voiceBtnRecording' : ''}`}
              disabled={voiceState !== 'idle' && voiceState !== 'recording'}
              onClick={handleVoiceButton}
              title={isRecording ? 'Stop recording and send' : 'Start voice chat'}
            >
              {isRecording ? '⏹ Stop & Send' : '🎤 Voice Chat'}
            </button>
            <VoiceBadge state={voiceState} />
          </div>

          {voiceTranscript && (
            <p className="voiceTranscript">
              <strong>You said:</strong> {voiceTranscript}
            </p>
          )}

          {/* ─ Text input ─ */}
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask VINU a question, or use voice chat above"
          />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={useCamera}
              onChange={(e) => setUseCamera(e.target.checked)}
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
