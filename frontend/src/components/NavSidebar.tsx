import type { StoredConversation } from '../conversations'
import { IconBars, IconChat, IconClock, IconClose, IconDatabase, IconHome, IconPlus, LeafLogo } from './Icons'

export type View = 'overview' | 'assistant' | 'analyses' | 'sources'

const NAV: { view: View; label: string; Icon: typeof IconHome }[] = [
  { view: 'overview', label: 'Overblik', Icon: IconHome },
  { view: 'assistant', label: 'AI-assistent', Icon: IconChat },
  { view: 'analyses', label: 'Analyser', Icon: IconBars },
  { view: 'sources', label: 'Datakilder', Icon: IconDatabase },
]

interface Props {
  view: View
  onView: (v: View) => void
  onNewChat: () => void
  conversations: StoredConversation[]
  activeConversation: string
  onOpenConversation: (c: StoredConversation) => void
  open: boolean
  onClose: () => void
  model?: string
}

export function NavSidebar({ view, onView, onNewChat, conversations, activeConversation, onOpenConversation, open, onClose, model }: Props) {
  return (
    <aside className={`nav ${open ? 'open' : ''}`} aria-label="Navigation">
      <div className="nav-head">
        <div className="brand">
          <LeafLogo />
          <span className="brand-name">MealMind Insights</span>
        </div>
        <button className="icon-btn nav-close" onClick={onClose} type="button" aria-label="Luk menu"><IconClose /></button>
      </div>

      <button className="btn btn-primary btn-block" onClick={onNewChat} type="button">
        <IconPlus /> Ny samtale
      </button>

      <nav className="nav-list">
        {NAV.map(({ view: v, label, Icon }) => (
          <button key={v} type="button" className={`nav-item ${view === v ? 'active' : ''}`} aria-current={view === v ? 'page' : undefined}
            onClick={() => onView(v)}>
            <Icon /> {label}
          </button>
        ))}
      </nav>

      <div className="nav-section">
        <div className="nav-section-title"><IconClock /> Seneste samtaler</div>
        {conversations.length === 0 ? (
          <p className="nav-empty">Dine samtaler gemmes her i browseren.</p>
        ) : (
          <ul className="nav-conversations">
            {conversations.map((c) => (
              <li key={c.id}>
                <button type="button" className={`nav-conversation ${c.id === activeConversation ? 'active' : ''}`}
                  onClick={() => onOpenConversation(c)} title={c.title}>
                  <IconChat size={18} /> <span>{c.title}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {model && <div className="nav-foot">AI-model: {model}</div>}
    </aside>
  )
}
