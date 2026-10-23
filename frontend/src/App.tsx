import { useCallback, useEffect, useRef, useState } from 'react'
import { AuthError, fetchDatasets, fetchHealth, historyFor, setToken, streamChat } from './api'
import { MessageView } from './components/MessageView'
import { Sidebar } from './components/Sidebar'
import { applyEvent } from './reducer'
import type { AssistantMessage, DatasetsResponse, Health, Message } from './types'

const SUGGESTIONS = [
  'Hvordan har antallet af aktive brugere udviklet sig måned for måned?',
  'Hvilke varekategorier bliver oftest spildt, og hvad koster spildet?',
  'Hvilke faktorer forudsiger, om en vare bliver spildt?',
  'Lav en prognose for de ugentlige madudgifter de næste 8 uger',
  'Kan brugerne inddeles i segmenter ud fra deres måltidsvaner?',
  'Springer brugere med AI-genererede madplaner færre måltider over?',
]

let idCounter = 0
const newId = () => `m${Date.now()}-${idCounter++}`

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [datasets, setDatasets] = useState<DatasetsResponse | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [needToken, setNeedToken] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [loadError, setLoadError] = useState('')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      setHealth(await fetchHealth())
      setDatasets(await fetchDatasets())
      setNeedToken(false)
      setLoadError('')
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      else setLoadError('Kan ikke forbinde til backend. Kører serveren?')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  async function send(text: string) {
    const question = text.trim()
    if (!question || busy) return
    const history = historyFor(messages)
    const assistantId = newId()
    const assistant: AssistantMessage = { role: 'assistant', id: assistantId, text: '', steps: [], visuals: [], status: 'streaming' }
    setMessages((m) => [...m, { role: 'user', id: newId(), text: question }, assistant])
    setInput('')
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller

    const update = (fn: (a: AssistantMessage) => AssistantMessage) =>
      setMessages((all) => all.map((m) => (m.id === assistantId && m.role === 'assistant' ? fn(m) : m)))

    try {
      await streamChat(question, history, (ev) => update((a) => applyEvent(a, ev)), controller.signal)
      update((a) => (a.status === 'streaming' ? { ...a, status: 'error', error: 'Forbindelsen blev afbrudt.' } : a))
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      const aborted = controller.signal.aborted
      update((a) => ({ ...a, status: 'error', error: aborted ? 'Stoppet.' : (e as Error).message }))
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  function newChat() {
    abortRef.current?.abort()
    setMessages([])
    setSidebarOpen(false)
  }

  const demo = health?.demo ?? datasets?.demo

  return (
    <div className="layout">
      <Sidebar health={health} datasets={datasets} onNewChat={newChat} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="main">
        <header className="topbar">
          <button className="ghost-btn menu-btn" onClick={() => setSidebarOpen(true)} type="button" aria-label="Vis datakilder">☰</button>
          <h1>MealMind AI Data Assistant</h1>
        </header>

        {demo && (
          <div className="demo-banner" role="status">
            <strong>DEMODATA</strong> Svarene bygger på syntetiske data genereret til afprøvning – ikke rigtige MealMind-brugere.
          </div>
        )}
        {health?.source_error && <div className="warn-banner" role="alert">{health.source_error}</div>}
        {health?.read_only_check?.status === 'write_access' && (
          <div className="warn-banner" role="alert">{health.read_only_check.message}</div>
        )}
        {health && !health.llm_configured && (
          <div className="warn-banner" role="alert">
            AI-modellen er ikke konfigureret. Sæt <code>{health.provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY'}</code> i <code>.env</code> og genstart backend.
          </div>
        )}
        {loadError && <div className="warn-banner" role="alert">{loadError}</div>}

        {needToken && (
          <form
            className="token-form"
            onSubmit={(e) => {
              e.preventDefault()
              setToken(tokenInput.trim())
              void load()
            }}
          >
            <label htmlFor="token">Adgangstoken</label>
            <input id="token" type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoComplete="off" />
            <button className="primary-btn" type="submit">Log ind</button>
          </form>
        )}

        <div className="thread">
          {messages.length === 0 ? (
            <div className="empty">
              <h2>Spørg om MealMind</h2>
              <p className="muted">
                Assistenten vælger selv mellem SQL, statistisk analyse og ML-modeller, og viser grafer, tabeller og forklaringer.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="suggestion" onClick={() => void send(s)} disabled={busy || needToken}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => <MessageView key={m.id} msg={m} />)
          )}
          <div ref={endRef} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            void send(input)
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send(input)
              }
            }}
            placeholder="Stil et spørgsmål om MealMind-data…"
            rows={1}
            maxLength={4000}
            aria-label="Spørgsmål"
            disabled={needToken}
          />
          {busy ? (
            <button type="button" className="secondary-btn" onClick={() => abortRef.current?.abort()}>Stop</button>
          ) : (
            <button type="submit" className="primary-btn" disabled={!input.trim() || needToken}>Send</button>
          )}
        </form>
      </main>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}
    </div>
  )
}
