import { createSseParser } from './sse'
import type { AgentEvent, DatasetsResponse, Health, Message, Overview } from './types'

const TOKEN_KEY = 'mealmind-insights-token'
// Navnet før omdøbningen til MealMind Insights; et gemt token flyttes automatisk til den nye nøgle.
const LEGACY_TOKEN_KEY = 'mealmind-assistant-token'

export class AuthError extends Error {}

export function getToken(): string {
  try {
    const current = localStorage.getItem(TOKEN_KEY)
    if (current) return current
    const legacy = localStorage.getItem(LEGACY_TOKEN_KEY)
    if (legacy) {
      localStorage.setItem(TOKEN_KEY, legacy)
      localStorage.removeItem(LEGACY_TOKEN_KEY)
      return legacy
    }
    return ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Privat vindue eller blokeret storage: tokenet gælder så kun for denne side-visning.
  }
  memoryToken = token
}

let memoryToken = ''

function headers(): HeadersInit {
  const token = getToken() || memoryToken
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: headers() })
  if (res.status === 401) throw new AuthError('Adgangstoken kræves')
  if (!res.ok) throw new Error(`Serverfejl (${res.status})`)
  return res.json() as Promise<T>
}

export const fetchHealth = () => getJson<Health>('/api/health')
export const fetchDatasets = () => getJson<DatasetsResponse>('/api/datasets')
export const fetchOverview = () => getJson<Overview>('/api/overview')

export function historyFor(messages: Message[]) {
  return messages
    .filter((m) => m.role === 'user' || (m.status === 'done' && m.text))
    .map((m) => ({ role: m.role, content: m.text }))
}

export async function streamChat(
  message: string,
  history: { role: string; content: string }[],
  onEvent: (ev: AgentEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers() },
    body: JSON.stringify({ message, history }),
    signal,
  })
  if (res.status === 401) throw new AuthError('Adgangstoken kræves')
  if (res.status === 429) throw new Error('For mange forespørgsler. Vent et øjeblik og prøv igen.')
  if (!res.ok || !res.body) throw new Error(`Serverfejl (${res.status})`)

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  const parse = createSseParser()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    for (const data of parse(value)) {
      try {
        onEvent(JSON.parse(data) as AgentEvent)
      } catch {
        // Ping-kommentarer og ufuldstændige events ignoreres.
      }
    }
  }
}
