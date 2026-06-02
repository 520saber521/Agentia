import { motion } from "framer-motion"
import { memo, useCallback } from "react"

const DOMAIN_COLORS: Record<string, string> = {
  frontend: "#38bdf8",
  backend: "#22c55e",
  database: "#f59e0b",
  test: "#a78bfa",
  docs: "#06b6d4",
  devops: "#f43f5e",
  agent_comm: "#e2e8f0",
}

const NODE_RADIUS = 26

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

export const AgentNode = memo(function AgentNode({
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

  const handlePointerDown = useCallback((event: React.PointerEvent) => {
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    onDragStart?.(id, event.clientX, event.clientY)
  }, [id, onDragStart])

  const handlePointerMove = useCallback((event: React.PointerEvent) => {
    if (event.buttons !== 1) return
    event.stopPropagation()
    onDrag?.(id, event.clientX, event.clientY)
  }, [id, onDrag])

  const handlePointerUp = useCallback((event: React.PointerEvent) => {
    event.stopPropagation()
    event.currentTarget.releasePointerCapture(event.pointerId)
    onDragEnd?.()
  }, [onDragEnd])

  const handlePointerCancel = useCallback((event: React.PointerEvent) => {
    event.stopPropagation()
    onDragEnd?.()
  }, [onDragEnd])

  return (
    <motion.g
      animate={{ x, y }}
      transition={{
        type: "spring",
        stiffness: 280,
        damping: 26,
        mass: 0.6,
      }}
      style={{ cursor: "grab", touchAction: "none" }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
    >
      <motion.circle
        cx={0}
        cy={0}
        r={NODE_RADIUS + 12}
        fill="none"
        stroke={color}
        strokeWidth={1}
        animate={{ opacity: isBusy ? 0.3 : 0.14, scale: isBusy ? [1, 1.1, 1] : 1 }}
        transition={isBusy
          ? { duration: 1.6, repeat: Infinity, ease: "easeInOut" }
          : { duration: 0.3 }
        }
      />

      {isBusy && (
        <motion.circle
          cx={0}
          cy={0}
          r={NODE_RADIUS + 6}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeDasharray="8 5"
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
        />
      )}

      <circle
        cx={0}
        cy={0}
        r={NODE_RADIUS}
        fill={isOrchestrator ? "#07111f" : "#05070a"}
        stroke={color}
        strokeWidth={2}
        filter={`drop-shadow(0 0 14px ${color}55)`}
      />

      <text
        x={0}
        y={-5}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={14}
        fontWeight={800}
        fill="#f8fafc"
        fontFamily="Cascadia Mono, Consolas, monospace"
      >
        {initials}
      </text>

      <text
        x={0}
        y={11}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={7}
        fill={color}
        fontFamily="Cascadia Mono, Consolas, monospace"
        letterSpacing={0}
      >
        {shortRole}
      </text>

      {agentName && (
        <text
          x={0}
          y={NODE_RADIUS + 14}
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={9}
          fill="#e2e8f0"
          fontFamily="system-ui, sans-serif"
        >
          {agentName.length > 14 ? agentName.slice(0, 14) + "\u2026" : agentName}
        </text>
      )}
    </motion.g>
  )
})
