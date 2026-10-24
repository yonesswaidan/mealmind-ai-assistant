import { conversationTitle } from './insights'
import type { Message } from './types'

/** Seneste samtaler gemmes kun i denne browser (localStorage) som en bekvemmelighed. */
const KEY = 'mealmind-insights-conversations'
const MAX_CONVERSATIONS = 12
const MAX_BYTES = 1_500_000

export interface StoredConversation {
  id: string
  title: string
  updatedAt: number
  messages: Message[]
}

export function loadConversations(): StoredConversation[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as StoredConversation[]) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

/** Gemmer/opdaterer en samtale øverst. Kun afsluttede svar gemmes; ældste samtaler fjernes ved pladsmangel. */
export function saveConversation(id: string, messages: Message[], now = Date.now()): StoredConversation[] {
  const finished = messages.filter((m) => m.role === 'user' || m.status !== 'streaming')
  if (!finished.some((m) => m.role === 'user')) return loadConversations()
  const entry: StoredConversation = { id, title: conversationTitle(finished), updatedAt: now, messages: finished }
  let list = [entry, ...loadConversations().filter((c) => c.id !== id)].slice(0, MAX_CONVERSATIONS)
  try {
    let json = JSON.stringify(list)
    while (json.length > MAX_BYTES && list.length > 1) {
      list = list.slice(0, -1)
      json = JSON.stringify(list)
    }
    localStorage.setItem(KEY, json)
  } catch {
    // Privat vindue eller fuld storage: samtalen gemmes bare ikke.
  }
  return list
}

export function deleteConversations(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ignoreres
  }
}
