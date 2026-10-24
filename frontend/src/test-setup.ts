import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Uden vitest-globals rydder Testing Library ikke selv op mellem tests.
afterEach(cleanup)

// jsdom har ingen ResizeObserver; Recharts' ResponsiveContainer kræver den.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
