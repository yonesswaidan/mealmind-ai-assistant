import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AuthError, fetchDatasets, fetchHealth, fetchOverview, historyFor, setToken, streamChat } from './api'
import { IconArrowUp, IconMenu, IconSpark, IconStop, LeafLogo } from './components/Icons'
import { InsightsPanel } from './components/InsightsPanel'
import { MessageView } from './components/MessageView'
import { NavSidebar, type View } from './components/NavSidebar'
import { AnalysesView, Hero, OverviewView, QuickActions, SourcesView } from './components/Views'
import { loadConversations, saveConversation, type StoredConversation } from './conversations'
import { MODE_TEXT, dataMode, executionNote } from './insights'
import { applyEvent } from './reducer'
import type { AssistantMessage, DatasetsResponse, Health, Message, Overview, SourceInfo } from './types'

let idCounter = 0
const newId = (prefix = 'm') => `${prefix}${Date.now()}-${idCounter++}`

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [datasets, setDatasets] = useState<DatasetsResponse | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [conversationId, setConversationId] = useState(() => newId('c'))
  const [conversations, setConversations] = useState<StoredConversation[]>(() => loadConversations())
  const [view, setView] = useState<View>('assistant')
  const [sourceFocus, setSourceFocus] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [needToken, setNeedToken] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [loadError, setLoadError] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  const load = useCallback(async () => {
    try {
      setHealth(await fetchHealth())
      const [ds, ov] = await Promise.all([fetchDatasets(), fetchOverview()])
      setDatasets(ds)
      setOverview(ov)
      setNeedToken(false)
      setLoadError('')
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      else setLoadError('Kan ikke forbinde til serveren. Kører backend?')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (view === 'assistant') endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, view])

  const mode = dataMode(health)
  const asked = useMemo(() => new Set(messages.filter((m) => m.role === 'user').map((m) => m.text)), [messages])
  const nextQuestions = (overview?.next_questions ?? []).filter((q) => !asked.has(q)).slice(0, 3)

  async function send(text: string) {
    const question = text.trim()
    if (!question || busy) return
    setView('assistant')
    setNavOpen(false)
    const history = historyFor(messages)
    const assistantId = newId()
    const assistant: AssistantMessage = { role: 'assistant', id: assistantId, text: '', steps: [], visuals: [], status: 'streaming' }
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
      update((a) => (a.status === 'streaming' ? { ...a, status: 'error', error: 'Forbindelsen blev afbrudt.' } : a))
    } catch (e) {
      if (e instanceof AuthError) setNeedToken(true)
      const aborted = controller.signal.aborted
      update((a) => ({ ...a, status: 'error', error: aborted ? 'Stoppet.' : (e as Error).message }))
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
    setMessages(c.messages)
    setConversationId(c.id)
    setView('assistant')
    setNavOpen(false)
  }

  function openSource(s?: SourceInfo) {
    setSourceFocus(s?.table ?? null)
    setView('sources')
  }

  const banners = (
    <>
      {health?.source_error && <div className="banner banner-warn" role="alert">{health.source_error}</div>}
      {health?.read_only_check?.status === 'write_access' && (
        <div className="banner banner-warn" role="alert">{health.read_only_check.message}</div>
      )}
      {health && !health.llm_configured && (
        <div className="banner banner-warn" role="alert">
          AI-modellen er ikke konfigureret. Sæt <code>{health.provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY'}</code> i <code>.env</code> og genstart backend.
        </div>
      )}
      {loadError && <div className="banner banner-warn" role="alert">{loadError}</div>}
      {needToken && (
        <form className="token-form" onSubmit={(e) => { e.preventDefault(); setToken(tokenInput.trim()); void load() }}>
          <label htmlFor="token">Adgangstoken</label>
          <input id="token" type="password" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} autoComplete="off" />
          <button className="btn btn-primary" type="submit">Log ind</button>
        </form>
      )}
    </>
  )

  return (
    <div className="app">
      <NavSidebar view={view} onView={(v) => { setView(v); setNavOpen(false) }} onNewChat={newChat}
        conversations={conversations} activeConversation={conversationId} onOpenConversation={openConversation}
        open={navOpen} onClose={() => setNavOpen(false)} model={health && health.provider !== 'test' ? health.model : undefined} />
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <div className="workspace">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setNavOpen(true)} type="button" aria-label="Åbn menu"><IconMenu /></button>
          <div className="topbar-brand"><LeafLogo size={26} /> MealMind Insights</div>
          {mode && (
            <span className={`mode-badge mode-${mode}`} role="status" title={health?.data_label}>
              <span className="dot" aria-hidden /> {MODE_TEXT[mode].badge}
            </span>
          )}
        </header>

        <div className="columns">
          <main className="main" id="main">
            {banners}
            {view === 'assistant' && (
              <section className="chat-card" aria-label="AI-assistent">
                <div className="thread">
                  <Hero compact={messages.length > 0} />
                  <QuickActions actions={overview?.quick_actions ?? []} onAsk={(q) => void send(q)} disabled={busy || needToken} />
                  {messages.map((m) => <MessageView key={m.id} msg={m} mode={mode} />)}
                  <div ref={endRef} />
                </div>
                <form className="composer" onSubmit={(e) => { e.preventDefault(); void send(input) }}>
                  <IconSpark className="composer-icon" />
                  <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input) }
                    }}
                    placeholder="Stil et spørgsmål om dine data…" rows={1} maxLength={4000} aria-label="Spørgsmål" disabled={needToken} />
                  {busy ? (
                    <button type="button" className="send-btn" onClick={() => abortRef.current?.abort()} aria-label="Stop"><IconStop /></button>
                  ) : (
                    <button type="submit" className="send-btn" disabled={!input.trim() || needToken} aria-label="Send"><IconArrowUp /></button>
                  )}
                </form>
              </section>
            )}
            {view === 'overview' && (
              <OverviewView overview={overview} mode={mode} questions={nextQuestions} onAsk={(q) => void send(q)}
                onOpenSources={() => openSource()} busy={busy || needToken} />
            )}
            {view === 'analyses' && (
              <AnalysesView messages={messages} onAsk={(q) => void send(q)} actions={overview?.quick_actions ?? []} busy={busy || needToken} />
            )}
            {view === 'sources' && <SourcesView datasets={datasets} overview={overview} mode={mode} focus={sourceFocus} />}
          </main>

          <aside className="side" aria-label="Datakilder og ML-status">
            <InsightsPanel overview={overview} mode={mode} questions={nextQuestions} onAsk={(q) => void send(q)}
              onOpenSource={openSource} busy={busy || needToken} />
            {mode && <p className="side-foot">{MODE_TEXT[mode].footer} · {executionNote(health)}</p>}
          </aside>
        </div>
      </div>
    </div>
  )
}
