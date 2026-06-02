import { useMemo } from "react"
import { useChatStore } from "../../stores/useChatStore"
import type { AnimAgentNode, AnimBeam, AnimEvent, CommEdge } from "./types"

const ORCHESTRATOR_ID = "agent_orchestrator"

export interface UseAgentGraphReturn {
  nodes: AnimAgentNode[]
  beams: AnimBeam[]
  events: AnimEvent[]
  commEdges: CommEdge[]
  nodeStatusMap: Record<string, "IDLE" | "BUSY" | "WAKING">
  orchestratorId: string | null
}

export function useAgentGraph(): UseAgentGraphReturn {
  const tasks = useChatStore((s) => s.tasks)
  const messages = useChatStore((s) => s.messages)
  const streamingIds = useChatStore((s) => s.streamingMessageIds)
  const currentConvId = useChatStore((s) => s.currentConvId)
  const conversations = useChatStore((s) => s.conversations)
  const agents = useChatStore((s) => s.agents)
  const graphNodes = useChatStore((s) => s.agentGraphNodes)
  const graphBeams = useChatStore((s) => s.agentGraphBeams)
  const graphEvents = useChatStore((s) => s.agentGraphEvents)
  const graphStatuses = useChatStore((s) => s.agentGraphStatuses)

  const { nodes, orchestratorId, beams, events, commEdges } = useMemo(() => {
    const taskList = currentConvId
      ? Object.values(tasks).filter((t) => t.conversation_id === currentConvId)
      : []

    const convMessages = currentConvId
      ? messages.filter((m) => m.conversation_id === currentConvId)
      : []
    const currentConv = conversations.find((c) => c.id === currentConvId)

    const nodeMap = new Map<string, AnimAgentNode>()
    const seenAgents = new Set<string>()

    const orchId = ORCHESTRATOR_ID
    nodeMap.set(orchId, {
      id: orchId,
      role: "Orchestrator",
      parentId: null,
      status: "IDLE",
      agentName: "Orchestrator",
    })

    for (const member of currentConv?.members ?? []) {
      if (member.member_type !== "agent" || member.member_id === orchId) continue
      const agent = agents.find((a) => a.id === member.member_id)
      const isStreaming = convMessages.some(
        (m) => m.sender_id === member.member_id && streamingIds.includes(m.id),
      )
      nodeMap.set(member.member_id, {
        id: member.member_id,
        role: agent?.capabilities[0] || agent?.adapter_type || "agent",
        parentId: orchId,
        status: isStreaming ? "BUSY" : "IDLE",
        domain: agent?.capabilities[0],
        agentName: agent?.name,
      })
      seenAgents.add(member.member_id)
    }

    for (const task of taskList) {
      const agentId = task.assigned_agent_id
      if (!agentId || agentId === orchId || seenAgents.has(agentId)) continue
      seenAgents.add(agentId)

      const isStreaming = convMessages.some(
        (m) =>
          m.sender_id === agentId &&
          streamingIds.includes(m.id),
      )

      nodeMap.set(agentId, {
        id: agentId,
        role: task.domain || "agent",
        parentId: orchId,
        status: isStreaming || task.status === "running" ? "BUSY" : "IDLE",
        domain: task.domain || undefined,
        agentName: task.agent_name || undefined,
      })
    }

    const beams: AnimBeam[] = []
    for (const task of taskList) {
      if (!task.assigned_agent_id || task.status === "planning") continue

      if (task.parent_task_id) {
        beams.push({
          id: `beam-${task.id}-orch`,
          fromId: orchId,
          toId: task.assigned_agent_id,
          kind: "create",
          label: task.title?.slice(0, 20) || "",
          createdAt: task.created_at,
        })
      }

      if (task.depends_on) {
        for (const depId of task.depends_on) {
          const depTask = taskList.find((t) => t.id === depId)
          if (depTask?.assigned_agent_id && task.assigned_agent_id) {
            beams.push({
              id: `beam-dep-${depId}-${task.id}`,
              fromId: depTask.assigned_agent_id,
              toId: task.assigned_agent_id,
              kind: "message",
              label: depTask.title?.slice(0, 20) || "",
              createdAt: task.created_at,
            })
          }
        }
      }
    }

    const events: AnimEvent[] = []
    for (const task of taskList) {
      if (task.status === "running") {
        events.push({
          id: `evt-${task.id}-running`,
          kind: "llm",
          label: `${task.agent_name || task.domain || "agent"}: 执行中`,
          at: task.updated_at || task.created_at,
        })
      } else if (task.status === "done") {
        events.push({
          id: `evt-${task.id}-done`,
          kind: "llm",
          label: `${task.agent_name || task.domain || "agent"}: 完成`,
          at: task.updated_at || task.created_at,
        })
      }
    }

    for (const msg of convMessages) {
      if (msg.sender_type === "agent") {
        events.push({
          id: `evt-msg-${msg.id}`,
          kind: "message",
          label: `消息: ${msg.sender_id.slice(0, 8)}`,
          at: msg.created_at,
        })
      }
    }

    const memberIds = new Set((currentConv?.members ?? []).map((m) => m.member_id))
    const edgeMap = new Map<string, CommEdge>()
    for (const msg of convMessages) {
      if (msg.sender_type !== "agent") continue
      const targets = msg.mentions?.length
        ? msg.mentions.filter((id) => id !== msg.sender_id)
        : Array.from(memberIds).filter((id) => id !== msg.sender_id && id !== "user_demo")
      for (const target of targets) {
        if (!nodeMap.has(target)) continue
        const key = `${msg.sender_id}->${target}`
        const existing = edgeMap.get(key)
        if (existing) {
          existing.count += 1
          existing.lastAt = Math.max(existing.lastAt, msg.created_at)
        } else {
          edgeMap.set(key, {
            fromId: msg.sender_id,
            toId: target,
            count: 1,
            lastAt: msg.created_at,
          })
        }
      }
    }

    return {
      nodes: Array.from(nodeMap.values()),
      orchestratorId: orchId,
      beams,
      events: events.sort((a, b) => b.at - a.at).slice(0, 50),
      commEdges: Array.from(edgeMap.values()).sort((a, b) => b.lastAt - a.lastAt).slice(0, 24),
    }
  }, [tasks, messages, streamingIds, currentConvId, conversations, agents])

  const mergedNodes = useMemo(() => {
    const map = new Map(nodes.map((node) => [node.id, node]))
    for (const node of Object.values(graphNodes)) {
      map.set(node.id, {
        ...node,
        status: graphStatuses[node.id] || node.status,
        domain: node.domain || undefined,
        agentName: node.agentName || undefined,
      })
    }
    return Array.from(map.values())
  }, [nodes, graphNodes, graphStatuses])

  const mergedBeams = useMemo(() => {
    const map = new Map(beams.map((beam) => [beam.id, beam]))
    for (const beam of graphBeams) {
      map.set(beam.id, beam)
    }
    return Array.from(map.values())
  }, [beams, graphBeams])

  const mergedEvents = useMemo(() => {
    const map = new Map<string, AnimEvent>()
    for (const event of graphEvents) map.set(event.id, event)
    for (const event of events) map.set(event.id, event)
    return Array.from(map.values()).sort((a, b) => b.at - a.at).slice(0, 80)
  }, [events, graphEvents])

  const nodeStatusMap = useMemo(() => {
    const map: Record<string, "IDLE" | "BUSY" | "WAKING"> = {}
    for (const node of mergedNodes) {
      map[node.id] = graphStatuses[node.id] || node.status
    }
    return map
  }, [mergedNodes, graphStatuses])

  return { nodes: mergedNodes, beams: mergedBeams, events: mergedEvents, commEdges, nodeStatusMap, orchestratorId }
}
