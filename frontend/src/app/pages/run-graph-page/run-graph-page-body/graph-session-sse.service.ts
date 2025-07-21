import { Injectable, signal } from '@angular/core';
import { GraphSessionStatus } from '../../../features/flows/services/flows-sessions.service';
import { GraphMessage } from '../../running-graph/models/graph-session-message.model';
import { Memory } from '../../running-graph/components/memory-sidebar/models/memory.model';
import { ConfigService } from '../../../services/config/config.service';

@Injectable()
export class RunSessionSSEService {
  constructor(private configService: ConfigService) {}

  private eventSource: EventSource | null = null;
  private currentSessionId: string | null = null;

  // Signals
  private messagesSignal = signal<GraphMessage[]>([]);
  private statusSignal = signal<GraphSessionStatus>(GraphSessionStatus.RUNNING);
  private memoriesSignal = signal<Memory[]>([]);
  private streamOpen = signal(false);

  public readonly isStreaming = this.streamOpen.asReadonly();
  public readonly messages = this.messagesSignal.asReadonly();
  public readonly status = this.statusSignal.asReadonly();
  public readonly memories = this.memoriesSignal.asReadonly();

  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private readonly reconnectDelayMs = 2000;

  private get apiUrl(): string {
    return `${this.configService.apiUrl}run-session/subscribe/${this.currentSessionId}`;
  }

  public startStream(sessionId: string): void {
    if (this.currentSessionId === sessionId && this.eventSource) return;
    this.cleanup();
    this.currentSessionId = sessionId;
    this.connect(sessionId);
  }

  public resumeStream(): void {
    if (!this.currentSessionId) return;
    this.connect(this.currentSessionId);
  }

  public stopStream(): void {
    this.disconnect();
  }

  private connect(sessionId: string): void {
    if (this.eventSource) {
      console.warn('SSE already started');
      return;
    }

    this.eventSource = new EventSource(this.apiUrl);

    this.eventSource.onopen = () => {
      console.log('SSE connection established');
      this.reconnectAttempts = 0;
      this.streamOpen.set(true);
    };

    this.eventSource.onmessage = (event) => {
      console.warn('Unnamed event received:', event.data);
    };

    this.eventSource.addEventListener('messages', (event: MessageEvent) => {
      const raw = JSON.parse(event.data);

      const msg: GraphMessage = {
        id: raw.id,
        uuid: raw.uuid,
        session: raw.session_id,
        name: raw.name,
        execution_order: raw.execution_order,
        created_at: raw.created_at || raw.timestamp,
        message_data: raw.message_data,
      };

      const messagesList = this.messages();
      const exists = messagesList.some((m) => m.uuid === msg.uuid);
      if (!exists) {
        messagesList.push(msg);
        messagesList.sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
        this.messagesSignal.set([...messagesList]);
      }
    });

    this.eventSource.addEventListener('status', (event: MessageEvent) => {
      const statusData = JSON.parse(event.data);
      this.statusSignal.set(statusData.status as GraphSessionStatus);
    });

    this.eventSource.addEventListener('memory', (event: MessageEvent) => {
      const memory = JSON.parse(event.data) as Memory;
      const memoriesList = this.memories();
      const existingIndex = memoriesList.findIndex((m) => m.id === memory.id);

      if (existingIndex !== -1) {
        // Update existing memory
        memoriesList[existingIndex] = memory;
      } else {
        // Add new memory
        memoriesList.push(memory);
      }

      this.memoriesSignal.set([...memoriesList]);
    });

    this.eventSource.addEventListener(
      'memory-delete',
      (event: MessageEvent) => {
        const memory = JSON.parse(event.data);
        const memoriesList = this.memories();
        const existingIndex = memoriesList.findIndex((m) => m.id === memory);

        if (existingIndex !== -1) {
          // Delete existing memory
          memoriesList.splice(existingIndex, 1);
          this.memoriesSignal.set([...memoriesList]);
        }
      }
    );

    this.eventSource.addEventListener('fatal-error', (event: MessageEvent) => {
      console.error('Fatal SSE error received');
      this.disconnect();
      this.reconnectAttempts = this.maxReconnectAttempts;
    });

    this.eventSource.onerror = (err) => {
      console.error('SSE error:', err);
      this.reconnect(sessionId);
    };
  }

  private reconnect(sessionId: string): void {
    if (!this.streamOpen) {
      console.warn('SSE service is inactive. Skipping reconnect.');
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max SSE reconnect attempts reached. Giving up.');
      this.eventSource?.close();
      this.eventSource = null;
      return;
    }

    if (this.eventSource?.readyState === EventSource.CLOSED) {
      console.warn('EventSource closed. Attempting to reconnect...');
    }

    this.eventSource?.close();
    this.eventSource = null;
    this.reconnectAttempts++;

    setTimeout(() => {
      this.startStream(sessionId);
    }, this.reconnectDelayMs * this.reconnectAttempts);
  }

  private disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      console.log('Stop SSE');
    }

    this.streamOpen.set(false);
  }

  private cleanup(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      console.log('Stop SSE');
    }

    this.reconnectAttempts = 0;
    this.currentSessionId = null;

    this.messagesSignal.set([]);
    this.memoriesSignal.set([]);
    this.statusSignal.set(GraphSessionStatus.RUNNING);
    this.streamOpen.set(false);
  }
}
