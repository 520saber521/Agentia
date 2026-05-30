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
  artifact_id?: string;
  code?: string;
  language?: string;
  title?: string;
  fileName?: string;
  mimeType?: string;
  fileSize?: number;
  url?: string;
  previewUrl?: string;
  version?: number;
}

export interface DiffContent {
  type: "diff";
  artifact_id?: string;
  before?: string;
  after?: string;
  diff?: string;
  base_artifact_id?: string;
  baseArtifactId?: string;
  summary?: string;
  fileName?: string;
  file_name?: string;
  mimeType?: string;
  fileSize?: number;
  applied_artifact_id?: string;
  version?: number;
}

export interface PreviewContent {
  type: "preview";
  artifact_id?: string;
  title: string;
  mimeType: string;
  fileSize?: number;
  url?: string;
  previewUrl?: string;
  version?: number;
}

export interface FileContent {
  type: "file";
  artifact_id?: string;
  fileName: string;
  mimeType: string;
  fileSize?: number;
  url?: string;
  previewUrl?: string;
  version?: number;
}

export interface TaskStatusContent {
  type: "task_status";
  task_id: string;
  status: "planning" | "pending" | "running" | "done" | "failed" | "blocked" | "conflict";
  title?: string;
  progress?: number;
  summary?: string;
}

export interface DeployStatusContent {
  type: "deploy_status";
  deploy_id: string;
  status: string;
  title?: string;
  url?: string;
  summary?: string;
  progress?: number;
}

export type MessageContent =
  | TextContent
  | CodeContent
  | DiffContent
  | PreviewContent
  | FileContent
  | TaskStatusContent
  | DeployStatusContent;

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
  /** 前端本地状态：该消息相关的工具调用记录（由 tool_call WS 事件填充） */
  toolCalls?: ToolCallInfo[];
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
  workspace_path: string | null;
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
  model: string;
  base_url: string;
  system_prompt: string;
  tools: string[];
  capabilities: string[];
  api_key_configured: boolean;
  api_key_mask: string;
  is_system: boolean;
  locked_prompt: boolean;
  can_delete: boolean;
  owner_user_id: string | null;
  created_at: number;
  updated_at: number;
}

export type ConnectionStatus = "disconnected" | "connecting" | "connected";

export type AgentGraphStatus = "IDLE" | "BUSY" | "WAKING";

export interface AgentGraphNode {
  id: string;
  role: string;
  parentId: string | null;
  status: AgentGraphStatus;
  domain?: string;
  agentName?: string;
}

export interface AgentGraphBeam {
  id: string;
  fromId: string;
  toId: string;
  kind: "create" | "message";
  label?: string;
  createdAt: number;
}

export interface AgentGraphEvent {
  id: string;
  kind: "agent" | "message" | "llm" | "tool";
  label: string;
  at: number;
}

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
    }
  | {
      type: "message_pinned";
      ts: number;
      conversation_id: string;
      message: Message;
    }
  | {
      type: "message_unpinned";
      ts: number;
      conversation_id: string;
      message: Message;
    }
  | {
      type: "context_info";
      ts: number;
      conversation_id: string;
      total_messages: number;
      pinned_messages: number;
      history_count?: number;
      estimated_tokens?: number;
      strategy?: string;
    }
  | {
      type: "tool_call";
      ts: number;
      message_id: string;
      sender_id?: string;
      conversation_id: string;
      tool_name: string;
      tool_arguments?: Record<string, unknown>;
      status: "running" | "done" | "error";
      result_summary?: string;
    }
  | {
      type: "tool_confirm_request";
      ts: number;
      message_id: string;
      sender_id?: string;
      conversation_id: string;
      confirm_id: string;
      tool_name: string;
      arguments: Record<string, unknown>;
    }
  | {
      type: "anim_agent_created";
      ts: number;
      event_id?: string;
      conversation_id: string;
      agent: {
        id: string;
        role: string;
        parentId: string | null;
        domain?: string | null;
        agentName?: string | null;
      };
    }
  | {
      type: "anim_agent_status";
      ts: number;
      event_id?: string;
      conversation_id: string;
      agentId: string;
      status: AgentGraphStatus;
    }
  | {
      type: "anim_beam";
      ts: number;
      event_id?: string;
      conversation_id: string;
      beam: {
        id: string;
        fromId: string;
        toId: string;
        kind: "create" | "message";
        label?: string | null;
      };
    }
  | {
      type: "anim_event";
      ts: number;
      event_id?: string;
      conversation_id: string;
      event: {
        id: string;
        kind: "agent" | "message" | "llm" | "tool";
        label: string;
      };
    }
  | {
      type: "workspace_file_changed";
      ts: number;
      conversation_id: string;
      path: string;
      action: "created" | "modified" | "deleted";
    }
  ;

export interface Attachment {
  artifact_id: string;
  file_name: string;
  mime_type: string;
  file_size: number;
}

export type ClientEvent =
  | { type: "ping" }
  | { type: "join"; conversation_id: string; limit?: number }
  | {
      type: "send_message";
      conversation_id: string;
      content: MessageContent;
      /** W2 F-W2-1：群聊 @mention 列表（agent_id 数组）。 */
      mentions?: string[];
      /** W4 F-W4-6：消息附件（已上传的 artifact_id 列表）。 */
      attachments?: Attachment[];
    }
  | { type: "cancel"; message_id: string }
  | { type: "tool_confirm_response"; confirm_id: string; approved: boolean }
  | {
      type: "deploy_status";
      ts: number;
      conversation_id: string;
      deploy_id: string;
      status: string;
      content: DeployStatusContent;
    }
  | {
      type: "shell_command_started";
      ts: number;
      conversation_id: string;
      command: string;
    }
  | {
      type: "shell_command_completed";
      ts: number;
      conversation_id: string;
      command: string;
      exit_code: number;
    }
;

/**
 * W3 F-W3-3: Task entity matching server/services/task.py task_to_dict().
 */
export interface Task {
  id: string;
  conversation_id: string;
  parent_task_id: string | null;
  title: string;
  description: string;
  status: "planning" | "pending" | "running" | "done" | "failed" | "blocked" | "conflict";
  domain: string | null;
  assigned_agent_id: string | null;
  agent_name: string | null;
  originating_message_id: string | null;
  result_summary: string | null;
  progress_pct: number;
  depends_on?: string[];
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
  url: string;
  preview_url: string;
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

/** 工具调用记录 — 由 tool_call WS 事件填充到 Message.toolCalls */
export interface ToolCallInfo {
  toolName: string;
  status: "running" | "done" | "error" | "skipped";
  resultSummary?: string;
  step?: number;
}

/** 文件浏览器条目 */
export interface FileEntry {
  name: string;
  type: "file" | "directory";
  size: number;
}

/** Workspace 文件树节点（递归） */
export interface FileTreeNode {
  name: string;
  type: "file" | "directory";
  path: string;
  size: number;
  children?: FileTreeNode[] | null;
  modified_at?: number;
  truncated?: boolean;
}
