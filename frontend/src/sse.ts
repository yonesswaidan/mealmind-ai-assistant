/** Inkrementel parser for text/event-stream. Returnerer data-felterne fra komplette events. */
export function createSseParser() {
  let buffer = ''
  return (chunk: string): string[] => {
    buffer += chunk.replace(/\r\n/g, '\n')
    const out: string[] = []
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = raw
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).replace(/^ /, ''))
        .join('\n')
      if (data) out.push(data)
    }
    return out
  }
}
