import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AuthError, fetchHealth, fetchOverview, historyFor, setToken, streamChat } from './api'
import { IconAlert, IconArrowUp, IconMenu, IconSpark, IconStop, LeafLogo } from './components/Icons'
import { MessageView } from './components/MessageView'
import { NavSidebar, type View } from './components/NavSidebar'
import { AnalysesView, Hero, OverviewView, SuggestionCards } from './components/Views'
import { loadConversations, saveConversation, type StoredConversation } from './conversations'
import { dataMode } from './insights'
import { suggestionsFrom } from './present'
import { applyEvent } from './reducer'
import type { AssistantMessage, Health, Message, Overview } from './types'

let idCounter = 0
const newId = (prefix = 'm') => `${prefix}${Date.now()}-${idCounter++}`
// Følg nye beskeder, så længe brugeren er tæt på bunden; har de scrollet op for at læse, flyttes de ikke.
const STICK_PX = 140

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState(() => newId('c'))
  const [conversations, setConversations] = useState<StoredConversation[]>(() => loadConversations())
  const [view, setView] = useState<View>('assistant')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [needToken, setNeedToken] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [loadError, setLoadError] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const threadRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  const load = useCallback(async () => {
    try {
      setHealth(await fetchHealth())
      setOverview(await fetchOverview())
      setNeedToken(false)
      setLoadError('')
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      else setLoadError('Kan ikke forbinde til serveren. Kontrollér, at MealMind Insights kører, og genindlæs siden.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const el = threadRef.current
    if (view === 'assistant' && el && stickRef.current) el.scrollTo({ top: el.scrollHeight })
  }, [messages, view])

  const mode = dataMode(health)
  const asked = useMemo(() => new Set(messages.filter((m) => m.role === 'user').map((m) => m.text)), [messages])
  const suggestions = useMemo(() => suggestionsFrom(overview), [overview])
  const nextQuestions = useMemo(() => {
    const all = [...(overview?.next_questions ?? []), ...(overview?.quick_actions.map((a) => a.question) ?? [])]
    return [...new Set(all)].filter((q) => !asked.has(q)).slice(0, 5)
  }, [overview, asked])

  async function send(text: string) {
    const question = text.trim()
    if (!question || busy) return
    setView('assistant')
    setNavOpen(false)
    stickRef.current = true
    const history = historyFor(messages)
    const assistantId = newId()
    const assistant: AssistantMessage = {
      role: 'assistant', id: assistantId, text: '', steps: [], visuals: [], status: 'streaming', createdAt: Date.now(),
    }
    const convId = conversationId
    let latest: Message[] = [...messages, { role: 'user', id: newId(), text: question }, assistant]
    setMessages(latest)
    setInput('')
    setBusy(true)
    const controller = new AbortController()
    abortRef.current = controller

    const update = (fn: (a: AssistantMessage) => AssistantMessage) => {
      latest = latest.map((m) => (m.id === assistantId && m.role === 'assistant' ? fn(m) : m))
      setMessages(latest)
    }

    try {
      await streamChat(question, history, (ev) => update((a) => applyEvent(a, ev)), controller.signal)
      update((a) => (a.status === 'streaming' ? { ...a, status: 'error', error: 'Forbindelsen blev afbrudt, før svaret var færdigt.' } : a))
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      const aborted = controller.signal.aborted
      const message = aborted ? 'Stoppet.' : e instanceof TypeError ? 'Kunne ikke nå serveren. Kontrollér forbindelsen og prøv igen.' : (e as Error).message
      update((a) => ({ ...a, status: 'error', error: message }))
    } finally {
      setBusy(false)
      abortRef.current = null
      setConversations(saveConversation(convId, latest))
    }
  }

  function newChat() {
    abortRef.current?.abort()
    setMessages([])
    setConversationId(newId('c'))
    setView('assistant')
    setNavOpen(false)
    inputRef.current?.focus()
  }

  function openConversation(c: StoredConversation) {
    abortRef.current?.abort()
    stickRef.current = true
    setMessages(c.messages)
    setConversationId(c.id)
    setView('assistant')
    setNavOpen(false)
  }

  const disabled = busy || needToken

  const banners = (
    <>
      {health?.source_error && <div className="banner" role="alert"><IconAlert size={18} /> {health.source_error}</div>}
      {health?.read_only_check?.status === 'write_access' && (
        <div className="banner" role="alert"><IconAlert size={18} /> {health.read_only_check.message}</div>
      )}
      {health && !health.llm_configured && (
        <div className="banner" role="alert">
          <IconAlert size={18} />
          <span>AI-modellen er ikke sat op. Indsæt <code>{health.provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY'}</code> i <code>.env</code> og genstart.</span>
        </div>
      )}
      {loadError && (
        <div className="banner" role="alert">
          <IconAlert size={18} /> <span>{loadError}</span>
          <button type="button" className="pill-btn" onClick={() => void load()}>Prøv igen</button>
        </div>
      )}
      {needToken && (
        <form className="token-form" onSubmit={(e) => { e.preventDefault(); setToken(tokenInput.trim()); void load() }}>
          <label htmlFor="token">Adgangstoken</label>
          <input id="token" type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoComplete="off" />
          <button className="btn btn-primary" type="submit">Log ind</button>
        </form>
      )}
    </>
  )

  // Hvert svar får det spørgsmål, det besvarer, som titel.
  let lastQuestion = ''
  const thread = messages.map((m) => {
    if (m.role === 'user') {
      lastQuestion = m.text
      return null
    }
    return <MessageView key={m.id} msg={m} mode={mode} question={lastQuestion} onRetry={(q) => void send(q)} />
  })

  return (
    <div className="app">
      <NavSidebar view={view} onView={(v) => { setView(v); setNavOpen(false) }} onNewChat={newChat}
        conversations={conversations} activeConversation={conversationId} onOpenConversation={openConversation}
        open={navOpen} onClose={() => setNavOpen(false)} model={health && health.provider !== 'test' ? health.model : undefined} />
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <div className="workspace">
        <header className="topbar">
          <button className="icon-btn" onClick={() => setNavOpen(true)} type="button" aria-label="Åbn menu"><IconMenu /></button>
          <div className="topbar-brand"><LeafLogo size={24} /> MealMind Insights</div>
        </header>

        {view === 'assistant' ? (
          <main className="chat" id="main" aria-label="AI-assistent">
            <div className="thread" ref={threadRef}
              onScroll={(e) => {
                const el = e.currentTarget
                stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_PX
              }}>
              <div className="thread-inner">
                {banners}
                <Hero compact={messages.length > 0} />
                <SuggestionCards items={suggestions} onAsk={(q) => void send(q)} disabled={disabled} />
                {thread}
              </div>
            </div>
            <div className="composer-row">
              <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(input) }}>
                <IconSpark className="composer-icon" />
                <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(input) }
                  }}
                  placeholder="Skriv dit spørgsmål her..." rows={1} maxLength={4000} aria-label="Spørgsmål" disabled={needToken} />
                {busy ? (
                  <button type="button" className="send-btn" onClick={() => abortRef.current?.abort()} aria-label="Stop"><IconStop /></button>
                ) : (
                  <button type="submit" className="send-btn" disabled={!input.trim() || needToken} aria-label="Send"><IconArrowUp /></button>
                )}
              </form>
            </div>
          </main>
        ) : (
          <main className="scroll-main" id="main">
            <div className="page-wrap">
              {banners}
              {view === 'overview' && (
                <OverviewView overview={overview} questions={nextQuestions} onAsk={(q) => void send(q)} busy={disabled} />
              )}
              {view === 'analyses' && (
                <AnalysesView messages={messages} onAsk={(q) => void send(q)} suggestions={suggestions} busy={disabled} />
              )}
            </div>
          </main>
        )}
      </div>
    </div>
  )
}
