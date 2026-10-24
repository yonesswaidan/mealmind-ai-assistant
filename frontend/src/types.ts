export type ChartType = 'bar' | 'line' | 'area' | 'scatter' | 'pie'
export type Cell = string | number | boolean | null

export interface ChartSpec {
  type: ChartType
  title: string
  x: string
  y: string[]
  stacked: boolean
  x_label?: string | null
  y_label?: string | null
  data: Record<string, Cell>[]
  notes: string[]
}

export interface TableSpec {
  title: string
  result_id: string
  columns: string[]
  rows: Record<string, Cell>[]
  total_rows: number
  sql?: string | null
}

export type AgentEvent =
  | { type: 'start'; demo: boolean; data_source: string }
  | { type: 'plan'; capabilities: string[]; labels: string[]; tools: string[]; ml_functions: string[]; notes: string[] }
  | { type: 'notice'; level: 'warning' | 'info'; message: string }
  | { type: 'text_delta'; text: string }
  | { type: 'text_break' }
  | { type: 'step'; id: string; tool: string; input: unknown }
  | { type: 'sql'; step_id: string; sql: string; row_count: number }
  | { type: 'ml'; step_id: string; function: string; summary: Record<string, unknown> }
  | { type: 'chart'; step_id: string; chart: ChartSpec }
  | { type: 'table'; step_id: string; table: TableSpec }
  | { type: 'step_done'; id: string; ok: boolean; summary: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

export interface Step {
  id: string
  tool: string
  input: unknown
  status: 'running' | 'ok' | 'error'
  summary?: string
  sql?: string
  rowCount?: number
  ml?: { function: string; summary: Record<string, unknown> }
}

export type Visual = { kind: 'chart'; id: string; chart: ChartSpec } | { kind: 'table'; id: string; table: TableSpec }

export interface UserMessage {
  role: 'user'
  id: string
  text: string
}

export interface AssistantMessage {
  role: 'assistant'
  id: string
  text: string
  steps: Step[]
  visuals: Visual[]
  status: 'streaming' | 'done' | 'error'
  error?: string
  demo?: boolean
  plan?: string[]
  notices?: string[]
}

export type Message = UserMessage | AssistantMessage

export interface DatasetColumn {
  name: string
  type: string
  description?: string
  sample_values: string[]
}

export interface Dataset {
  name: string
  description: string
  row_count: number | null
  columns: DatasetColumn[]
}

export interface DatasetsResponse {
  demo: boolean
  data_source: string
  data_label?: string
  tables: Dataset[]
  ml_functions: { name: string; description: string }[]
}

export interface Health {
  status: string
  data_source: string
  data_label?: string
  demo: boolean
  llm_configured: boolean
  provider: 'openai' | 'anthropic' | 'test'
  model: string
  test_mode: boolean
  auth_required: boolean
  source_error?: string | null
  read_only_check?: { status: 'ok' | 'write_access' | 'unknown'; message: string } | null
}

export interface SourceInfo {
  table: string
  title: string
  kind: 'meals' | 'shopping' | 'ml' | 'other'
  rows: number | null
  origin: 'demo' | 'real'
  description: string
}

export interface QuickAction {
  label: string
  icon: 'chart' | 'search' | 'dish'
  question: string
}

export interface MlStatus {
  name: string
  title: string
  status: string
  label: string
  detail: string
  source: 'databricks' | 'local'
}

export interface Overview {
  data_source: string
  data_label: string
  demo: boolean
  sources: SourceInfo[]
  quick_actions: QuickAction[]
  next_questions: string[]
  ml_status: MlStatus[]
}
