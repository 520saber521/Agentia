/**
 * 自研轻量 WS 客户端。
 *
 * 设计要点（对应 `docs/ARCHITECTURE.md` §7.2 的"可靠性"小节）：
 * - 25s 心跳；连续两次 pong 丢失即视为断开（由浏览器原生 close 触发）。
 * - 指数退避重连：1 / 2 / 4 / 8 / 16 / 30 秒封顶。
 * - 显式 `disconnect()` 不会重连。
 */

import type { ClientEvent, ConnectionStatus, ServerEvent } from "../types";

type EventListener = (evt: ServerEvent) => void;
type StatusListener = (status: ConnectionStatus) => void;
type ConnectedListener = () => void;

const HEARTBEAT_INTERVAL_MS = 25_000;
const RECONNECT_MAX_MS = 30_000;

export class WSClient {
  private readonly url: string;
  private ws: WebSocket | null = null;
  private readonly listeners = new Set<EventListener>();
  private readonly statusListeners = new Set<StatusListener>();
  private readonly connectedListeners = new Set<ConnectedListener>();
  private heartbeatTimer: number | null = null;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private explicitClose = false;
  private status: ConnectionStatus = "disconnected";

  constructor(url?: string) {
    if (url) {
      this.url = url;
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      this.url = `${proto}//${window.location.host}/ws`;
    }
  }

  connect(): void {
    if (
      this.ws &&
      (this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }
    this.explicitClose = false;
    this.setStatus("connecting");

    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.addEventListener("open", this.handleOpen);
    ws.addEventListener("close", this.handleClose);
    ws.addEventListener("error", this.handleError);
    ws.addEventListener("message", this.handleMessage);
  }

  disconnect(): void {
    this.explicitClose = true;
    this.clearHeartbeat();
    this.clearReconnect();
    this.ws?.close();
    this.ws = null;
    this.setStatus("disconnected");
  }

  send(evt: ClientEvent): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn("[ws] drop event, socket not open", evt);
      return false;
    }
    this.ws.send(JSON.stringify(evt));
    return true;
  }

  onEvent(fn: EventListener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => {
      this.statusListeners.delete(fn);
    };
  }

  onConnected(fn: ConnectedListener): () => void {
    this.connectedListeners.add(fn);
    return () => {
      this.connectedListeners.delete(fn);
    };
  }

  private setStatus(s: ConnectionStatus): void {
    this.status = s;
    this.statusListeners.forEach((l) => l(s));
  }

  private readonly handleOpen = (): void => {
    this.reconnectAttempt = 0;
    this.setStatus("connected");
    this.startHeartbeat();
    this.connectedListeners.forEach((l) => l());
  };

  private readonly handleClose = (): void => {
    this.clearHeartbeat();
    this.setStatus("disconnected");
    if (!this.explicitClose) {
      this.scheduleReconnect();
    }
  };

  private readonly handleError = (): void => {
    // 浏览器 close 事件会紧跟而来，重连交给 handleClose。
  };

  private readonly handleMessage = (e: MessageEvent<string>): void => {
    try {
      const evt = JSON.parse(e.data) as ServerEvent;
      this.listeners.forEach((l) => l(evt));
    } catch (err) {
      console.error("[ws] bad JSON", err, e.data);
    }
  };

  private startHeartbeat(): void {
    this.clearHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      this.send({ type: "ping" });
    }, HEARTBEAT_INTERVAL_MS);
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    this.clearReconnect();
    const backoff = Math.min(
      RECONNECT_MAX_MS,
      1000 * Math.pow(2, this.reconnectAttempt),
    );
    this.reconnectAttempt += 1;
    console.info(
      `[ws] reconnect in ${backoff}ms (attempt #${this.reconnectAttempt})`,
    );
    this.reconnectTimer = window.setTimeout(() => this.connect(), backoff);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
