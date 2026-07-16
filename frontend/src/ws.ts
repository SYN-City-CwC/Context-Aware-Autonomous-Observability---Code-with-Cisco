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
    const socket = new WebSocket(backendWsUrl());
    this.socket = socket;
    socket.addEventListener("open", () => {
      if (this.socket === socket) {
        this.handlers.onOpen();
      }
    });
    socket.addEventListener("close", () => {
      if (this.socket === socket) {
        this.handlers.onClose();
      }
    });
    socket.addEventListener("error", () => {
      if (this.socket === socket) {
        this.handlers.onError();
      }
    });
    socket.addEventListener("message", (event) => {
      if (this.socket !== socket) {
        return;
      }
      this.handlers.onMessage(JSON.parse(event.data) as ReplayMessage);
    });
  }

  close(): void {
    const socket = this.socket;
    this.socket = null;
    if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) {
      socket.close();
    }
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
