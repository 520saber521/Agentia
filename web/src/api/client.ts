/**
 * REST 客户端。封装 BFF 的 `/api/*` 端点；错误统一抛 `ApiError`，由调用方决定如何提示。
 *
 * W2 F-W2-5 起：
 * - 区分 4xx 业务错（带 `code` 稳定枚举）与 5xx 网络错；
 * - `ApiError.code` 让 UI 能展示具体文案（如"群聊需要至少 1 个 Agent"）。
 */

import type { Agent, Artifact, Attachment, Conversation, FileTreeNode, Message } from "../types";

/**
 * 后端业务错误的稳定枚举码（与 `server/api/rest.py` 的 detail 一致）。
 * 不在白名单内的 detail 会归到 `unknown` —— 让调用方做兜底文案。
 */
export type ApiErrorCode =
  | "title required"
  | "invalid_type"
  | "group_requires_agents"
  | "unknown_agent"
  | "artifact_conflict"
  | "invalid_content"
  | "unknown";

export class ApiError extends Error {
  status: number;
  code: ApiErrorCode;
  detail: string;

  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
    const KNOWN: ApiErrorCode[] = [
      "title required",
      "invalid_type",
      "group_requires_agents",
      "unknown_agent",
      "artifact_conflict",
      "invalid_content",
    ];
    this.code = (KNOWN as string[]).includes(detail)
      ? (detail as ApiErrorCode)
      : "unknown";
    this.name = "ApiError";
  }
}

async function parseErrorDetail(r: Response): Promise<string> {
  try {
    const data: unknown = await r.json();
    if (data && typeof data === "object" && "detail" in data) {
      const d = (data as { detail: unknown }).detail;
      if (typeof d === "string") return d;
      // Pydantic 422 返回 `detail: [{msg, ...}, ...]`，取 msg 拼接
      if (Array.isArray(d)) {
        return d
          .map((it) =>
            it && typeof it === "object" && "msg" in it
              ? String((it as { msg: unknown }).msg)
              : JSON.stringify(it),
          )
          .join("; ");
      }
      return JSON.stringify(d);
    }
  } catch {
    // ignore parse error
  }
  return r.statusText || `HTTP ${r.status}`;
}

async function getJson<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
  return (await r.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
  return (await r.json()) as T;
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "PUT",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
  return (await r.json()) as T;
}

async function deleteJson(path: string): Promise<void> {
  const r = await fetch(path, { method: "DELETE", headers: { Accept: "application/json" } });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
}

export interface FetchConversationOptions {
  includeArchived?: boolean;
  q?: string;
}

export async function fetchConversations(
  options: FetchConversationOptions = {},
): Promise<Conversation[]> {
  const params = new URLSearchParams();
  if (options.includeArchived) params.set("include_archived", "true");
  if (options.q?.trim()) params.set("q", options.q.trim());
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const body = await getJson<{ conversations: Conversation[] }>(
    `/api/conversations${suffix}`,
  );
  return body.conversations;
}

export async function fetchMessages(
  conversationId: string,
  limit = 200,
): Promise<Message[]> {
  const body = await getJson<{
    conversation_id: string;
    messages: Message[];
    limit: number;
  }>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`,
  );
  return body.messages;
}

export async function fetchAgents(): Promise<Agent[]> {
  const body = await getJson<{ agents: Agent[] }>("/api/agents");
  return body.agents;
}

export interface SaveAgentInput {
  name: string;
  adapter_type?: string;
  api_key?: string;
  model?: string;
  base_url?: string;
  system_prompt?: string;
  tools?: string[];
  capabilities?: string[];
  avatar?: string | null;
}

export async function createAgent(input: SaveAgentInput): Promise<Agent> {
  const body = await postJson<{ agent: Agent }>("/api/agents", input);
  return body.agent;
}

export async function updateAgent(
  agentId: string,
  input: Partial<SaveAgentInput>,
): Promise<Agent> {
  const body = await putJson<{ agent: Agent }>(
    `/api/agents/${encodeURIComponent(agentId)}`,
    input,
  );
  return body.agent;
}

export async function deleteAgent(agentId: string): Promise<void> {
  await deleteJson(`/api/agents/${encodeURIComponent(agentId)}`);
}

export interface AgentPromptResponse {
  agent_id: string;
  prompt: string;
  prompt_file: string;
  is_system: boolean;
}

export async function fetchAgentPrompt(agentId: string): Promise<AgentPromptResponse> {
  const body = await getJson<AgentPromptResponse>(
    `/api/agents/${encodeURIComponent(agentId)}/prompt`,
  );
  return body;
}

export interface CreateConversationInput {
  title: string;
  type?: "single" | "group";
  agent_ids?: string[];
}

export async function createConversation(
  input: CreateConversationInput,
): Promise<Conversation> {
  const body = await postJson<{ conversation: Conversation }>(
    "/api/conversations",
    {
      title: input.title,
      type: input.type ?? "single",
      agent_ids: input.agent_ids ?? [],
    },
  );
  return body.conversation;
}

export interface UpdateConversationInput {
  title?: string;
  pinned?: boolean;
  archived?: boolean;
}

export async function updateConversation(
  conversationId: string,
  input: UpdateConversationInput,
): Promise<Conversation> {
  const r = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
  const body = (await r.json()) as { conversation: Conversation };
  return body.conversation;
}

// ---------------------------------------------------------------------------
// Artifact API (F-W4-2 / F-W4-4)
// ---------------------------------------------------------------------------

export interface FetchArtifactContentResult {
  content: string;
}

export interface SaveArtifactVersionInput {
  conversation_id: string;
  kind: string;
  title: string;
  mime_type: string;
  content: string;
  parent_id?: string;
  file_name?: string;
  source_message_id?: string;
  meta?: Record<string, unknown>;
}

export interface ApplyDiffInput {
  base_artifact_id: string;
  before: string;
  after: string;
  summary?: string;
  file_name?: string;
  source_message_id?: string;
}

export async function fetchArtifactContent(
  artifactId: string,
): Promise<string> {
  const body = await getJson<FetchArtifactContentResult>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/content`,
  );
  return body.content;
}

export async function fetchArtifact(artifactId: string): Promise<Artifact> {
  const body = await getJson<{ artifact: Artifact }>(
    `/api/artifacts/${encodeURIComponent(artifactId)}`,
  );
  return body.artifact;
}

export async function uploadFile(
  file: File,
  conversationId: string,
): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);
  const url = `/api/upload?conversation_id=${encodeURIComponent(conversationId)}`;
  const r = await fetch(url, { method: "POST", body: form });
  if (!r.ok) throw new ApiError(r.status, await parseErrorDetail(r));
  const body = (await r.json()) as { artifact: Artifact };
  return {
    artifact_id: body.artifact.id,
    file_name: body.artifact.file_name ?? file.name,
    mime_type: body.artifact.mime_type,
    file_size: body.artifact.file_size,
  };
}

export async function saveArtifactVersion(
  input: SaveArtifactVersionInput,
): Promise<Artifact> {
  const body = await postJson<{ artifact: Artifact; message?: Message | null }>("/api/artifacts", input);
  return body.artifact;
}

export async function createArtifactMessage(
  input: SaveArtifactVersionInput,
): Promise<{ artifact: Artifact; message: Message | null }> {
  return postJson<{ artifact: Artifact; message: Message | null }>(
    "/api/artifacts",
    input,
  );
}

export async function fetchArtifactHistory(
  artifactId: string,
): Promise<Artifact[]> {
  const body = await getJson<{ artifact_id: string; history: Artifact[] }>(
    `/api/artifacts/${encodeURIComponent(artifactId)}/history`,
  );
  return body.history;
}

export async function createInvalidContentProbe(): Promise<void> {
  await postJson("/api/artifacts", {
    conversation_id: "conv_demo",
    kind: "invalid-kind",
    title: "invalid",
    mime_type: "text/plain",
    content: "invalid",
  });
}

export async function applyDiffArtifact(
  input: ApplyDiffInput,
): Promise<{ artifact: Artifact; message: Message }> {
  return postJson<{ artifact: Artifact; message: Message }>(
    `/api/artifacts/${encodeURIComponent(input.base_artifact_id)}/apply-diff`,
    {
      before: input.before,
      after: input.after,
      summary: input.summary,
      file_name: input.file_name,
      source_message_id: input.source_message_id,
    },
  );
}

/**
 * 把 `ApiError.code` 翻译成中文文案，用于模态错误提示。
 * 不属于 `ApiErrorCode` 白名单的 fallback 到通用文案。
 */
export function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "title required":
        return "会话标题不能为空";
      case "invalid_type":
        return "会话类型只能是 single 或 group";
      case "group_requires_agents":
        return "群聊需要至少 1 个 Agent";
      case "unknown_agent":
        return "选择的 Agent 中存在无效项，请刷新成员列表";
      case "artifact_conflict":
        return "目标产物已有新版本，请先打开最新版本或重新生成 Diff";
      case "invalid_content":
        return "消息内容格式不合法，请检查类型和必填字段";
      case "unknown":
        return err.detail || "请求失败，请稍后再试";
    }
  }
  if (err instanceof Error) return err.message;
  return "请求失败，请稍后再试";
}

// ---------------------------------------------------------------------------
// Pin / Unpin API
// ---------------------------------------------------------------------------

export async function pinMessage(messageId: string): Promise<Message> {
  const body = await postJson<{ message: Message }>(
    `/api/messages/${encodeURIComponent(messageId)}/pin`,
    {},
  );
  return body.message;
}

export async function unpinMessage(messageId: string): Promise<Message> {
  const body = await postJson<{ message: Message }>(
    `/api/messages/${encodeURIComponent(messageId)}/unpin`,
    {},
  );
  return body.message;
}

export interface ContextStats {
  conversation_id: string;
  total_messages: number;
  pinned_messages: number;
}

export async function fetchContextStats(
  conversationId: string,
): Promise<ContextStats> {
  return getJson<ContextStats>(
    `/api/conversations/${encodeURIComponent(conversationId)}/context-stats`,
  );
}

// ---------------------------------------------------------------------------
// Workspace API
// ---------------------------------------------------------------------------

export interface WorkspaceTreeResponse {
  conversation_id: string;
  root_path: string;
  path: string;
  tree: FileTreeNode[];
}

export interface WorkspaceFileResponse {
  path: string;
  content: string;
  size: number;
  mime_type: string;
}

export async function fetchWorkspaceTree(
  conversationId: string,
  path = "",
): Promise<WorkspaceTreeResponse> {
  const qs = path ? `?path=${encodeURIComponent(path)}` : "";
  return getJson<WorkspaceTreeResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}/workspace/tree${qs}`,
  );
}

export async function fetchWorkspaceFile(
  conversationId: string,
  filePath: string,
): Promise<WorkspaceFileResponse> {
  return getJson<WorkspaceFileResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}/workspace/file?path=${encodeURIComponent(filePath)}`,
  );
}

export async function setWorkspacePath(
  conversationId: string,
  path: string,
): Promise<{ conversation_id: string; workspace_path: string; tree: FileTreeNode[] }> {
  return postJson(
    `/api/conversations/${encodeURIComponent(conversationId)}/workspace`,
    { path },
  );
}
