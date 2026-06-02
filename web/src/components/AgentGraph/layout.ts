import type { AnimAgentNode, LayoutNode } from "./types"

export function computeTreeLayout(
  nodes: AnimAgentNode[],
  humanId: string | null,
  nodeOffsets: Record<string, { x: number; y: number }>,
  viewport: { width: number; height: number } = { width: 800, height: 320 },
): LayoutNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const childrenById = new Map<string, AnimAgentNode[]>()
  const roots: AnimAgentNode[] = []

  for (const node of nodes) {
    if (!node.parentId || !byId.has(node.parentId)) {
      roots.push(node)
    } else {
      const children = childrenById.get(node.parentId) || []
      children.push(node)
      childrenById.set(node.parentId, children)
    }
  }

  roots.sort((a, b) => {
    if (humanId && a.id === humanId) return -1
    if (humanId && b.id === humanId) return 1
    if (a.id === "agent_orchestrator") return -1
    if (b.id === "agent_orchestrator") return 1
    return a.role.localeCompare(b.role)
  })

  let leafIndex = 0
  let maxDepth = 0
  const meta = new Map<string, { xIndex: number; depth: number }>()
  const visited = new Set<string>()

  function dfs(node: AnimAgentNode, depth: number): { min: number; max: number } {
    if (visited.has(node.id)) {
      const found = meta.get(node.id)
      const xIndex = found?.xIndex ?? 0
      return { min: xIndex, max: xIndex }
    }
    visited.add(node.id)
    maxDepth = Math.max(maxDepth, depth)
    const children = childrenById.get(node.id) || []
    if (children.length === 0) {
      const xIndex = leafIndex
      leafIndex++
      meta.set(node.id, { xIndex, depth })
      return { min: xIndex, max: xIndex }
    }
    const ranges = children.map((c) => dfs(c, depth + 1))
    const min = ranges[0]?.min ?? leafIndex
    const max = ranges[ranges.length - 1]?.max ?? min
    meta.set(node.id, { xIndex: (min + max) / 2, depth })
    return { min, max }
  }

  for (const root of roots) {
    dfs(root, 0)
  }

  const paddingX = 78
  const paddingY = 54
  const width = Math.max(320, viewport.width)
  const height = Math.max(180, viewport.height)
  const leafCount = Math.max(1, leafIndex)
  const depthCount = Math.max(1, maxDepth + 1)
  const xSpan = Math.max(1, width - paddingX * 2)
  const ySpan = Math.max(1, height - paddingY * 2)
  const xStep = leafCount === 1 ? 0 : xSpan / (leafCount - 1)
  const yStep = depthCount === 1 ? 0 : ySpan / (depthCount - 1)
  const result: LayoutNode[] = []

  for (const node of nodes) {
    const found = meta.get(node.id)
    if (!found) continue
    result.push({
      id: node.id,
      x: paddingX + found.xIndex * xStep,
      y: paddingY + found.depth * yStep,
      role: node.role,
      parentId: node.parentId,
    })
  }

  const offsetMap = new Map<string, { dx: number; dy: number }>()
  function collectOffset(id: string, dx: number, dy: number) {
    const existing = offsetMap.get(id) || { dx: 0, dy: 0 }
    offsetMap.set(id, { dx: existing.dx + dx, dy: existing.dy + dy })
    const children = childrenById.get(id) || []
    for (const child of children) {
      collectOffset(child.id, dx, dy)
    }
  }
  for (const [id, offset] of Object.entries(nodeOffsets)) {
    collectOffset(id, offset.x, offset.y)
  }

  for (const node of result) {
    const off = offsetMap.get(node.id)
    if (off) {
      node.x += off.dx
      node.y += off.dy
    }
  }

  return result
}
