import { motion } from "framer-motion"

interface Props {
  beamId: string
  fromX: number
  fromY: number
  toX: number
  toY: number
  kind: "create" | "message"
  label?: string
  onComplete: (beamId: string) => void
}

export function AgentBeam({ beamId, fromX, fromY, toX, toY, kind, label, onComplete }: Props) {
  const color = kind === "create" ? "#38bdf8" : "#f8fafc"
  const dashArray = kind === "create" ? "8 6" : "0"

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: 0.85 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
    >
      <motion.line
        x1={fromX}
        y1={fromY}
        x2={toX}
        y2={toY}
        stroke={color}
        strokeWidth={kind === "create" ? 2.4 : 1.6}
        strokeDasharray={dashArray}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: kind === "create" ? 0.55 : 0.34 }}
        transition={{ duration: 0.5 }}
      />

      <motion.circle
        r={kind === "create" ? 7 : 4}
        fill={color}
        initial={{ cx: fromX, cy: fromY, opacity: 0 }}
        animate={{ cx: toX, cy: toY, opacity: 1 }}
        transition={{ duration: 0.8, ease: "easeInOut" }}
        style={{ filter: `drop-shadow(0 0 ${kind === "create" ? 12 : 6}px ${color})` }}
        onAnimationComplete={() => onComplete(beamId)}
      />

      {label && (
        <foreignObject x={(fromX + toX) / 2 - 76} y={(fromY + toY) / 2 - 34} width={152} height={32}>
          <div className={`mx-auto w-fit max-w-[140px] truncate rounded-full border px-2 py-1 text-[10px] font-semibold ${
            kind === "create"
              ? "border-sky-400/50 bg-sky-950/70 text-sky-100"
              : "border-zinc-500/50 bg-zinc-950/80 text-zinc-100"
          }`}>
            {kind === "create" ? `create ${label}` : label}
          </div>
        </foreignObject>
      )}
    </motion.g>
  )
}
