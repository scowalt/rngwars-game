import {
  HubConnectionBuilder,
  HubConnection,
  HubConnectionState,
  HttpTransportType,
  LogLevel,
} from "@microsoft/signalr";
import type {
  QueueUpdate,
  MatchFound,
  PhaseChanged,
  MatchCompleted,
  MatchCancelled,
} from "../types";

export type SignalREvents = {
  onQueueUpdate: (data: QueueUpdate) => void;
  onMatchFound: (data: MatchFound) => void;
  onPhaseChanged: (data: PhaseChanged) => void;
  onMatchCompleted: (data: MatchCompleted) => void;
  onMatchCancelled: (data: MatchCancelled) => void;
  onConnected: () => void;
  onDisconnected: () => void;
};

class SignalRService {
  private connection: HubConnection | null = null;
  private events: Partial<SignalREvents> = {};

  on<K extends keyof SignalREvents>(event: K, handler: SignalREvents[K]) {
    this.events[event] = handler;
  }

  async connect(token: string): Promise<void> {
    if (this.connection) {
      try {
        await this.connection.stop();
      } catch {}
      this.connection = null;
    }

    const isDev = import.meta.env.DEV;
    this.connection = new HubConnectionBuilder()
      .withUrl(`/hubs/game?access_token=${token}`, {
        ...(isDev
          ? { transport: HttpTransportType.ServerSentEvents | HttpTransportType.LongPolling }
          : {}),
      })
      .withAutomaticReconnect()
      .configureLogging(LogLevel.Warning)
      .build();

    this.connection.on("QueueUpdate", (data: QueueUpdate) => {
      this.events.onQueueUpdate?.(data);
    });

    this.connection.on("MatchFound", (data: MatchFound) => {
      this.events.onMatchFound?.(data);
    });

    this.connection.on("PhaseChanged", (data: PhaseChanged) => {
      this.events.onPhaseChanged?.(data);
    });

    this.connection.on("MatchCompleted", (data: MatchCompleted) => {
      this.events.onMatchCompleted?.(data);
    });

    this.connection.on("MatchCancelled", (data: MatchCancelled) => {
      this.events.onMatchCancelled?.(data);
    });

    this.connection.onreconnected(() => {
      this.events.onConnected?.();
    });

    this.connection.onclose(() => {
      this.events.onDisconnected?.();
    });

    await this.connection.start();
    this.events.onConnected?.();
  }

  async disconnect(): Promise<void> {
    if (this.connection) {
      await this.connection.stop();
      this.connection = null;
    }
  }

  async joinQueue(): Promise<void> {
    await this.connection?.invoke("JoinQueue");
  }

  async leaveQueue(): Promise<void> {
    await this.connection?.invoke("LeaveQueue");
  }

  async joinMatch(matchId: string): Promise<void> {
    await this.connection?.invoke("JoinMatch", matchId);
  }

  get isConnected(): boolean {
    return this.connection?.state === HubConnectionState.Connected;
  }
}

export const signalr = new SignalRService();
