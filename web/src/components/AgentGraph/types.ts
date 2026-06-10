export interface AnimAgentNode {
  id: string
  role: string
  parentId: string | null
  status: "IDLE" | "BUSY" | "WAKING"
  domain?: string
  agentName?: string
}

export interface AnimBeam {
  id: string
  fromId: string
  toId: string
  kind: "create" | "message"
  label?: string
  createdAt: number
}

export interface AnimEvent {
  id: string
  kind: "agent" | "message" | "llm" | "tool"
  label: string
  at: number
}

export interface LayoutNode {
  id: string
  x: number
  y: number
  role: string
  parentId: string | null
}

export interface CommEdge {
  fromId: string
  toId: string
  count: number
  lastAt: number
}
