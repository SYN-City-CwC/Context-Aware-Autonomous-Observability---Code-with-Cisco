import type { ReplayMessage } from "./types";

const DEFAULT_BACKEND_URL = "http://localhost:8000";

export type ReplaySocketHandlers = {
  onMessage: (message: ReplayMessage) => void;
  onOpen: () => void;
  onClose: () => void;
  onError: () => void;
};

export class ReplaySocket {
  private socket: WebSocket | null = null;

  constructor(private readonly handlers: ReplaySocketHandlers) {}

  connect(): void {
    this.close();
    this.socket = new WebSocket(backendWsUrl());
    this.socket.addEventListener("open", this.handlers.onOpen);
    this.socket.addEventListener("close", this.handlers.onClose);
    this.socket.addEventListener("error", this.handlers.onError);
    this.socket.addEventListener("message", (event) => {
      this.handlers.onMessage(JSON.parse(event.data) as ReplayMessage);
    });
  }

  close(): void {
    if (this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) {
      this.socket.close();
    }
    this.socket = null;
  }

  send(command: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command));
    }
  }

  isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }
}

export function backendHttpUrl(): string {
  return (import.meta.env.VITE_BACKEND_URL as string | undefined) ?? DEFAULT_BACKEND_URL;
}

function backendWsUrl(): string {
  const url = new URL(backendHttpUrl());
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/replay";
  url.search = "";
  return url.toString();
}
