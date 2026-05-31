import { motion } from "framer-motion"

const DOMAIN_COLORS: Record<string, string> = {
  frontend: "#38bdf8",
  backend: "#22c55e",
  database: "#f59e0b",
  test: "#a78bfa",
  docs: "#06b6d4",
  devops: "#f43f5e",
  agent_comm: "#e2e8f0",
}

const NODE_SIZE = 58

interface Props {
  id: string
  role: string
  x: number
  y: number
  status: "IDLE" | "BUSY" | "WAKING"
  agentName?: string
  domain?: string
  isOrchestrator?: boolean
  onDragStart?: (id: string, clientX: number, clientY: number) => void
  onDrag?: (id: string, clientX: number, clientY: number) => void
  onDragEnd?: () => void
}

export function AgentNode({
  id,
  role,
  x,
  y,
  status,
  agentName,
  domain,
  isOrchestrator,
  onDragStart,
  onDrag,
  onDragEnd,
}: Props) {
  const normalizedDomain = (domain || "").toLowerCase()
  const color = DOMAIN_COLORS[normalizedDomain] || "#38bdf8"
  const isBusy = status === "BUSY"
  const shortRole = isOrchestrator
    ? "ORCH"
    : (domain || role || "agent").slice(0, 7).toUpperCase()
  const initials =
    (agentName || shortRole)
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "AG"

  return (
    <motion.g
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0, opacity: 0 }}
      transition={{ type: "spring", stiffness: 220, damping: 18 }}
      style={{ cursor: "grab", touchAction: "none" }}
      onPointerDown={(event) => {
        event.stopPropagation()
        event.currentTarget.setPointerCapture(event.pointerId)
        onDragStart?.(id, event.clientX, event.clientY)
      }}
      onPointerMove={(event) => {
        if (event.buttons !== 1) return
        event.stopPropagation()
        onDrag?.(id, event.clientX, event.clientY)
      }}
      onPointerUp={(event) => {
        event.stopPropagation()
        event.currentTarget.releasePointerCapture(event.pointerId)
        onDragEnd?.()
      }}
      onPointerCancel={(event) => {
        event.stopPropagation()
        onDragEnd?.()
      }}
    >
      <motion.circle
        cx={x}
        cy={y}
        r={NODE_SIZE / 2 + 15}
        fill="none"
        stroke={color}
        strokeWidth={1}
        opacity={status === "IDLE" ? 0.16 : 0.32}
        animate={isBusy ? { scale: [1, 1.12, 1], opacity: [0.3, 0.08, 0.3] } : undefined}
        transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
        style={{ transformOrigin: `${x}px ${y}px` }}
      />

      {isBusy && (
        <motion.circle
          cx={x}
          cy={y}
          r={NODE_SIZE / 2 + 8}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeDasharray="9 5"
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
          style={{ transformOrigin: `${x}px ${y}px` }}
        />
      )}

      <circle
        cx={x}
        cy={y}
        r={NODE_SIZE / 2}
        fill={isOrchestrator ? "#07111f" : "#05070a"}
        stroke={color}
        strokeWidth={2}
        filter={`drop-shadow(0 0 18px ${color}55)`}
      />

      <text
        x={x}
        y={y - 6}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={15}
        fontWeight={800}
        fill="#f8fafc"
        fontFamily="Cascadia Mono, Consolas, monospace"
      >
        {initials}
      </text>

      <text
        x={x}
        y={y + 13}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={7.5}
        fill={color}
        fontFamily="Cascadia Mono, Consolas, monospace"
        letterSpacing={0}
      >
        {shortRole}
      </text>

      {agentName && (
        <text
          x={x}
          y={y + NODE_SIZE / 2 + 16}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={9.5}
          fill="#e2e8f0"
          fontFamily="system-ui, sans-serif"
        >
          {agentName.length > 16 ? agentName.slice(0, 16) + "\u2026" : agentName}
        </text>
      )}
    </motion.g>
  )
}
