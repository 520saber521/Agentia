/**
 * 与 server 的事件契约对齐（见 `server/main.py` 与 `docs/ARCHITECTURE.md` §7）。
 *
 * 这里只覆盖 W1 Day1-3 已经接通的消息类型；Day5+ 接入 Router 后扩展
 * `task_status` / `presence` / `usage` 等更多事件时，再在这里追加。
 */

export type SenderType = "user" | "agent";

export interface TextContent {
  type: "text";
  text: string;
}

export interface CodeContent {
  type: "code";
  code: string;
  language?: string;
  title?: string;
}

export interface DiffContent {
  type: "diff";
  before: string;
  after: string;
  fileName?: string;
}

export interface PreviewContent {
  type: "preview";
  title: string;
  mimeType: string;
  fileSize?: number;
}

export interface FileContent {
  type: "file";
  fileName: string;
  mimeType: string;
  fileSize?: number;
}

export type MessageContent =
  | TextContent
  | CodeContent
  | DiffContent
  | PreviewContent
  | FileContent
  | { type: "task_status"; [key: string]: unknown }
  | { type: string; [key: string]: unknown };

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_type: SenderType;
  content_type: string;
  content: MessageContent;
  reply_to: string | null;
  mentions: string[];
  pinned: boolean;
  artifact_id: string | null;
  agenthub_msg_id: string | null;
  created_at: number;
}

export interface Member {
  member_id: string;
  member_type: SenderType;
  role: string | null;
  joined_at: number;
}

export interface Conversation {
  id: string;
  title: string;
  type: "single" | "group";
  created_at: number;
  updated_at: number;
  pinned: boolean;
  archived: boolean;
  last_msg_preview: string | null;
  owner_user_id: string;
  members: Member[];
}

/**
 * Agent 实体（与 `server/services/agent.py` 的 `agent_to_dict` 对齐）。
 * W2 F-W2-5 起被 `NewConversationDialog` / 后续 `AgentManage` 页消费。
 *
 * 注意：`config`（含 api_key 等敏感字段）**不通过 REST 暴露**，前端永远拿不到。
 */
export interface Agent {
  id: string;
  name: string;
  avatar: string | null;
  adapter_type: string;
  capabilities: string[];
  owner_user_id: string | null;
  created_at: number;
}

export type ConnectionStatus = "disconnected" | "connecting" | "connected";

export type ServerEvent =
  | { type: "hello"; ts: number; conn_id: string; server: string }
  | { type: "pong"; ts: number }
  | { type: "echo"; ts: number; message_id: string; payload: unknown }
  | {
      type: "history";
      ts: number;
      conversation_id: string;
      messages: Message[];
      count: number;
    }
  | { type: "message_created"; ts: number; message: Message }
  | {
      type: "agent_typing";
      ts: number;
      agent_id: string;
      conversation_id: string;
    }
  | {
      type: "stream_chunk";
      ts: number;
      message_id: string;
      /** W2 F-W2-1：群聊 fan-out 时由后端冗余下发，便于前端按 sender 兜底匹配。 */
      sender_id?: string;
      conversation_id: string;
      seq: number;
      delta: string;
    }
  | {
      type: "message_done";
      ts: number;
      message_id: string;
      sender_id?: string;
      conversation_id: string;
      final_content: MessageContent;
    }
  | {
      type: "message_cancelled";
      ts: number;
      message_id: string;
      sender_id?: string;
      conversation_id: string;
      final_content: MessageContent;
    }
  | {
      type: "usage";
      ts: number;
      message_id: string;
      sender_id?: string;
      input_tokens: number;
      output_tokens: number;
    }
  | {
      type: "error";
      ts: number;
      code: string;
      message: string;
      message_id?: string;
      sender_id?: string;
      conversation_id?: string;
      /** W2 F-W2-1：部分降级路径标志（含未知 mention 但其它合法目标仍 fan-out）。 */
      degraded?: boolean;
    }
  | {
      type: "agents";
      ts: number;
      agents: Agent[];
    }
  | {
      type: "task_update";
      ts: number;
      conversation_id: string;
      task: Task;
      action: TaskUpdateAction;
    }
  | {
      type: "artifact_ready";
      ts: number;
      conversation_id: string;
      artifact: Artifact;
      message_id: string | null;
    };

export type ClientEvent =
  | { type: "ping" }
  | { type: "join"; conversation_id: string; limit?: number }
  | {
      type: "send_message";
      conversation_id: string;
      content: MessageContent;
      /** W2 F-W2-1：群聊 @mention 列表（agent_id 数组）。 */
      mentions?: string[];
    }
  | { type: "cancel"; message_id: string };

/**
 * W3 F-W3-3: Task entity matching server/services/task.py task_to_dict().
 */
export interface Task {
  id: string;
  conversation_id: string;
  parent_task_id: string | null;
  title: string;
  description: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  domain: string | null;
  assigned_agent_id: string | null;
  originating_message_id: string | null;
  result_summary: string | null;
  progress_pct: number;
  created_at: number;
  updated_at: number;
}

/** W3 F-W3-2: task_update event variants. */
export type TaskUpdateAction = "created" | "status_changed" | "completed";

export interface TaskUpdateEvent {
  type: "task_update";
  ts: number;
  conversation_id: string;
  task: Task;
  action: TaskUpdateAction;
}

/**
 * W4 F-W4-2: Artifact entity matching server/services/artifact.py artifact_to_dict().
 */
export interface Artifact {
  id: string;
  conversation_id: string;
  parent_id: string | null;
  kind: "code" | "preview" | "file" | "diff";
  title: string;
  mime_type: string;
  file_name: string | null;
  file_size: number;
  storage_path: string;
  source_message_id: string | null;
  created_by: string;
  meta: Record<string, unknown>;
  version: number;
  created_at: number;
}

/** W4 F-W4-2: artifact_ready WS event. */
export interface ArtifactReadyEvent {
  type: "artifact_ready";
  ts: number;
  conversation_id: string;
  artifact: Artifact;
  message_id: string | null;
}
