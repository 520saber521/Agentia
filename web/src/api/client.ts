/**
 * REST 客户端。封装 BFF 的 `/api/*` 端点；错误统一抛 `ApiError`，由调用方决定如何提示。
 *
 * W2 F-W2-5 起：
 * - 区分 4xx 业务错（带 `code` 稳定枚举）与 5xx 网络错；
 * - `ApiError.code` 让 UI 能展示具体文案（如"群聊需要至少 1 个 Agent"）。
 */

import type { Agent, Conversation, Message } from "../types";

/**
 * 后端业务错误的稳定枚举码（与 `server/api/rest.py` 的 detail 一致）。
 * 不在白名单内的 detail 会归到 `unknown` —— 让调用方做兜底文案。
 */
export type ApiErrorCode =
  | "title required"
  | "invalid_type"
  | "group_requires_agents"
  | "unknown_agent"
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

export async function fetchConversations(): Promise<Conversation[]> {
  const body = await getJson<{ conversations: Conversation[] }>(
    "/api/conversations",
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
      case "unknown":
        return err.detail || "请求失败，请稍后再试";
    }
  }
  if (err instanceof Error) return err.message;
  return "请求失败，请稍后再试";
}
