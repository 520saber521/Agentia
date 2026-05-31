import { useState, useCallback, useRef, useEffect, useMemo } from "react"
import { AnimatePresence, motion } from "framer-motion"
import { useAgentGraph } from "./useAgentGraph"
import { computeTreeLayout } from "./layout"
import { AgentNode } from "./AgentNode"
import { AgentBeam } from "./AgentBeam"
import type { AnimBeam } from "./types"

interface Props {
  width?: number
  height?: number
}

export function AgentGraph({ width: initialWidth = 900, height: initialHeight = 220 }: Props) {
  const { nodes, beams, events, commEdges, nodeStatusMap, orchestratorId } = useAgentGraph()
  const containerRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ width: initialWidth, height: initialHeight })
  const [vizOffset, setVizOffset] = useState({ x: 0, y: 0 })
  const [vizScale, setVizScale] = useState(0.94)
  const [nodeOffsets, setNodeOffsets] = useState<Record<string, { x: number; y: number }>>({})
  const [activeBeams, setActiveBeams] = useState<AnimBeam[]>([])
  const [showEvents, setShowEvents] = useState(true)
  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0, ox: 0, oy: 0 })
  const draggedNode = useRef<{
    id: string
    startClientX: number
    startClientY: number
    baseOffset: { x: number; y: number }
  } | null>(null)
  const dragFrame = useRef<number | null>(null)
  const pendingDrag = useRef<{ id: string; clientX: number; clientY: number } | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const rect = entry.contentRect
        if (!rect.width || !rect.height) continue
        setViewport({ width: rect.width, height: rect.height })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const layoutNodes = useMemo(
    () => computeTreeLayout(nodes, null, nodeOffsets, viewport),
    [nodes, nodeOffsets, viewport],
  )
  const layoutMap = useMemo(
    () => new Map(layoutNodes.map((n) => [n.id, n])),
    [layoutNodes],
  )
  const edgeList = useMemo(
    () => layoutNodes.filter((node) => node.parentId).map((node) => ({
      fromId: node.parentId as string,
      toId: node.id,
    })),
    [layoutNodes],
  )
  const commEdgeList = useMemo(
    () => commEdges
      .map((edge) => ({
        ...edge,
        from: layoutMap.get(edge.fromId),
        to: layoutMap.get(edge.toId),
      }))
      .filter((edge) => edge.from && edge.to),
    [commEdges, layoutMap],
  )
  const busyCount = nodes.filter((node) => (nodeStatusMap[node.id] || node.status) === "BUSY").length

  const handleBeamComplete = useCallback((beamId: string) => {
    setActiveBeams((prev) => prev.filter((b) => b.id !== beamId))
  }, [])

  useEffect(() => {
    setActiveBeams((prev) => {
      const existingIds = new Set(prev.map((b) => b.id))
      const additions = beams.filter((b) => !existingIds.has(b.id))
      return additions.length > 0 ? [...prev, ...additions].slice(-14) : prev
    })
  }, [beams])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if ((e.target as Element).closest("[data-agent-graph-control]")) return
    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY, ox: vizOffset.x, oy: vizOffset.y }
  }, [vizOffset])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning.current) return
    setVizOffset({
      x: panStart.current.ox + e.clientX - panStart.current.x,
      y: panStart.current.oy + e.clientY - panStart.current.y,
    })
  }, [])

  const handleMouseUp = useCallback(() => {
    isPanning.current = false
  }, [])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return
    e.preventDefault()
    setVizScale((s) => Math.min(2, Math.max(0.5, s + (e.deltaY > 0 ? -0.05 : 0.05))))
  }, [])

  const handleNodeDragStart = useCallback((id: string, clientX: number, clientY: number) => {
    isPanning.current = false
    draggedNode.current = {
      id,
      startClientX: clientX,
      startClientY: clientY,
      baseOffset: nodeOffsets[id] || { x: 0, y: 0 },
    }
  }, [nodeOffsets])

  const handleNodeDrag = useCallback((id: string, clientX: number, clientY: number) => {
    pendingDrag.current = { id, clientX, clientY }
    if (dragFrame.current !== null) return
    dragFrame.current = requestAnimationFrame(() => {
      dragFrame.current = null
      const next = pendingDrag.current
      const drag = draggedNode.current
      if (!next || !drag || drag.id !== next.id) return
      const dx = (next.clientX - drag.startClientX) / vizScale
      const dy = (next.clientY - drag.startClientY) / vizScale
      setNodeOffsets((prev) => ({
        ...prev,
        [next.id]: {
          x: drag.baseOffset.x + dx,
          y: drag.baseOffset.y + dy,
        },
      }))
    })
  }, [vizScale])

  const handleNodeDragEnd = useCallback(() => {
    draggedNode.current = null
    pendingDrag.current = null
    if (dragFrame.current !== null) {
      cancelAnimationFrame(dragFrame.current)
      dragFrame.current = null
    }
  }, [])

  if (nodes.length <= 1) return null

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden border-border bg-[#05070a]"
      style={{ height: initialHeight }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
    >
      <div
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "linear-gradient(rgba(56,189,248,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,0.08) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
          maskImage: "radial-gradient(circle at 50% 45%, black, transparent 78%)",
        }}
      />
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_16%_18%,rgba(56,189,248,0.18),transparent_34%),radial-gradient(circle_at_82%_72%,rgba(34,197,94,0.12),transparent_38%)]" />

      <div className="absolute left-4 top-3 z-10 flex items-center gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-200">
            Agent Mesh
          </div>
          <div className="mt-0.5 text-[10px] text-muted">
            {nodes.length} nodes / {busyCount} active / {events.length} events
          </div>
        </div>
      </div>

      <div data-agent-graph-control className="absolute right-3 top-3 z-10 flex items-center gap-1">
        <button
          onClick={() => setVizScale((s) => Math.min(2, s + 0.1))}
          className="h-7 w-7 rounded border border-border bg-bg/80 text-xs text-muted hover:text-fg"
          title="Zoom in"
        >
          +
        </button>
        <button
          onClick={() => setVizScale((s) => Math.max(0.5, s - 0.1))}
          className="h-7 w-7 rounded border border-border bg-bg/80 text-xs text-muted hover:text-fg"
          title="Zoom out"
        >
          -
        </button>
        <button
          onClick={() => { setVizOffset({ x: 0, y: 0 }); setVizScale(0.94); setNodeOffsets({}) }}
          className="h-7 rounded border border-border bg-bg/80 px-2 text-[10px] text-muted hover:text-fg"
        >
          Reset
        </button>
        <button
          onClick={() => setShowEvents((v) => !v)}
          className={`h-7 rounded border px-2 text-[10px] ${
            showEvents ? "border-sky-400/50 text-sky-200" : "border-border text-muted"
          } bg-bg/80`}
        >
          Events
        </button>
      </div>

      <svg
        width={viewport.width}
        height={viewport.height}
        viewBox={`0 0 ${viewport.width} ${viewport.height}`}
        className="absolute inset-0 cursor-grab active:cursor-grabbing"
      >
        <g transform={`translate(${vizOffset.x}, ${vizOffset.y}) scale(${vizScale})`}>
          <g>
            {edgeList.map((edge) => {
              const from = layoutMap.get(edge.fromId)
              const to = layoutMap.get(edge.toId)
              if (!from || !to) return null
              const midY = (from.y + to.y) / 2
              return (
                <path
                  key={`${edge.fromId}-${edge.toId}`}
                  d={`M ${from.x} ${from.y} L ${from.x} ${midY} L ${to.x} ${midY} L ${to.x} ${to.y}`}
                  stroke="rgba(148,163,184,0.34)"
                  strokeWidth={1.2}
                  fill="none"
                />
              )
            })}
          </g>

          <g>
            {commEdgeList.map((edge) => {
              if (!edge.from || !edge.to) return null
              const opacity = Math.min(0.56, 0.16 + edge.count * 0.06)
              const strokeWidth = Math.min(3.2, 1 + edge.count * 0.32)
              return (
                <g key={`${edge.fromId}-${edge.toId}`}>
                  <line
                    x1={edge.from.x}
                    y1={edge.from.y}
                    x2={edge.to.x}
                    y2={edge.to.y}
                    stroke="rgba(248,250,252,0.8)"
                    strokeWidth={strokeWidth}
                    strokeOpacity={opacity}
                    strokeDasharray="2 8"
                  />
                  <foreignObject
                    x={(edge.from.x + edge.to.x) / 2 - 18}
                    y={(edge.from.y + edge.to.y) / 2 - 12}
                    width={36}
                    height={24}
                  >
                    <div className="mx-auto w-fit rounded-full border border-zinc-500/50 bg-zinc-950/80 px-1.5 py-0.5 text-[9px] font-semibold text-zinc-200">
                      {edge.count}
                    </div>
                  </foreignObject>
                </g>
              )
            })}
          </g>

          <AnimatePresence>
            {activeBeams.map((beam) => {
              const fromNode = layoutMap.get(beam.fromId)
              const toNode = layoutMap.get(beam.toId)
              if (!fromNode || !toNode) return null
              return (
                <AgentBeam
                  key={beam.id}
                  beamId={beam.id}
                  fromX={fromNode.x}
                  fromY={fromNode.y}
                  toX={toNode.x}
                  toY={toNode.y}
                  kind={beam.kind}
                  label={beam.label}
                  onComplete={handleBeamComplete}
                />
              )
            })}
          </AnimatePresence>

          <AnimatePresence>
            {layoutNodes.map((node) => (
              <AgentNode
                key={node.id}
                id={node.id}
                role={node.role}
                x={node.x}
                y={node.y}
                status={nodeStatusMap[node.id] || "IDLE"}
                agentName={nodes.find((n) => n.id === node.id)?.agentName}
                domain={nodes.find((n) => n.id === node.id)?.domain}
                isOrchestrator={node.id === orchestratorId}
                onDragStart={handleNodeDragStart}
                onDrag={handleNodeDrag}
                onDragEnd={handleNodeDragEnd}
              />
            ))}
          </AnimatePresence>
        </g>
      </svg>

      <AnimatePresence>
        {showEvents && (
          <motion.div
            data-agent-graph-control
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            className="absolute bottom-3 right-3 z-10 w-72 max-w-[42%] rounded-lg border border-border bg-bg/90 p-3 shadow-2xl backdrop-blur"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted">
                Event Stream
              </div>
              <span className="rounded border border-border px-1.5 py-0.5 text-[9px] text-muted">
                {events.length}
              </span>
            </div>
            <div className="max-h-32 space-y-1 overflow-y-auto">
              {events.slice(0, 7).map((evt) => (
                <div key={evt.id} className="flex items-center gap-2 rounded border border-border/60 bg-panel/40 px-2 py-1.5">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    evt.kind === "llm" ? "bg-sky-400" :
                    evt.kind === "tool" ? "bg-amber-400" :
                    evt.kind === "message" ? "bg-emerald-400" :
                    "bg-purple-400"
                  }`} />
                  <span className="min-w-0 truncate text-[10px] text-fg/80">{evt.label}</span>
                </div>
              ))}
              {events.length === 0 && (
                <div className="rounded border border-dashed border-border px-3 py-3 text-center text-[10px] text-muted">
                  Waiting for agent activity
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
