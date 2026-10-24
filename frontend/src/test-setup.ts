import '@testing-library/jest-dom/vitest'

// jsdom har ingen ResizeObserver; Recharts' ResponsiveContainer kræver den.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
