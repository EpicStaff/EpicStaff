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
  private reconnectTimeout: any = null;

  // Signals
  private messagesSignal = signal<GraphMessage[]>([]);
  private statusSignal = signal<GraphSessionStatus>(GraphSessionStatus.RUNNING);
  private memoriesSignal = signal<Memory[]>([]);
  private streamOpen = signal(false);
  private connectionStatusSignal = signal<
    | 'connected'
    | 'connecting'
    | 'disconnected'
    | 'reconnecting'
    | 'manually_disconnected'
  >('disconnected');

  public readonly isStreaming = this.streamOpen.asReadonly();
  public readonly messages = this.messagesSignal.asReadonly();
  public readonly status = this.statusSignal.asReadonly();
  public readonly memories = this.memoriesSignal.asReadonly();
  public readonly connectionStatus = this.connectionStatusSignal.asReadonly();

  // Reconnection configuration
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private readonly baseReconnectDelayMs = 1000;
  private readonly maxReconnectDelayMs = 30000;
  private isManualDisconnect = false;

  private get apiUrl(): string {
    return `${this.configService.apiUrl}run-session/subscribe/${this.currentSessionId}`;
  }

  public startStream(sessionId: string): void {
    if (this.currentSessionId === sessionId && this.eventSource) return;
    this.cleanup();
    this.currentSessionId = sessionId;
    this.isManualDisconnect = false;
    this.connect(sessionId);
  }

  public resumeStream(): void {
    if (!this.currentSessionId) return;
    this.isManualDisconnect = false;
    this.connect(this.currentSessionId);
  }

  public stopStream(): void {
    this.isManualDisconnect = true;
    this.disconnect();
    // Set to manually_disconnected to distinguish from actual connection loss
    this.connectionStatusSignal.set('manually_disconnected');
  }

  private connect(sessionId: string): void {
    if (this.eventSource) {
      console.warn('SSE already started');
      return;
    }

    this.connectionStatusSignal.set('connecting');
    this.eventSource = new EventSource(this.apiUrl);

    this.eventSource.onopen = () => {
      console.log('SSE connection established');
      this.reconnectAttempts = 0;
      this.streamOpen.set(true);
      this.connectionStatusSignal.set('connected');
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
      this.handleConnectionLoss();
    });

    this.eventSource.onerror = (err) => {
      console.error('SSE error:', err);
      this.handleConnectionLoss();
    };
  }

  private handleConnectionLoss(): void {
    if (this.isManualDisconnect) {
      console.log('Manual disconnect - not attempting reconnection');
      return;
    }

    this.connectionStatusSignal.set('reconnecting');
    this.streamOpen.set(false);

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(
        `Max SSE reconnect attempts (${this.maxReconnectAttempts}) reached. Giving up.`
      );
      this.finalDisconnect();
      return;
    }

    this.reconnectAttempts++;
    const delay = this.calculateReconnectDelay();

    console.log(
      `Connection lost. Attempting reconnection ${this.reconnectAttempts}/${this.maxReconnectAttempts} in ${delay}ms`
    );
    console.log(`Current session ID: ${this.currentSessionId}`);

    this.reconnectTimeout = setTimeout(() => {
      if (!this.isManualDisconnect && this.currentSessionId) {
        console.log(
          `Attempting to reconnect to session: ${this.currentSessionId}`
        );
        this.connect(this.currentSessionId);
      } else {
        console.log(
          'Reconnection cancelled - manual disconnect or no session ID'
        );
      }
    }, delay);
  }

  private calculateReconnectDelay(): number {
    // Exponential backoff with jitter to prevent thundering herd
    const exponentialDelay =
      this.baseReconnectDelayMs * Math.pow(2, this.reconnectAttempts - 1);
    const jitter = Math.random() * 0.1 * exponentialDelay; // 10% jitter
    const finalDelay = Math.min(
      exponentialDelay + jitter,
      this.maxReconnectDelayMs
    );

    console.log(
      `Reconnect delay calculation: base=${this.baseReconnectDelayMs}, attempt=${this.reconnectAttempts}, exponential=${exponentialDelay}, jitter=${jitter}, final=${finalDelay}`
    );

    return finalDelay;
  }

  private finalDisconnect(): void {
    console.log('Final disconnect after max reconnection attempts');
    this.disconnect();
    this.connectionStatusSignal.set('disconnected');
  }

  private disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      console.log('SSE connection closed');
    }

    this.streamOpen.set(false);
    this.connectionStatusSignal.set('disconnected');
  }

  private cleanup(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      console.log('SSE cleanup completed');
    }

    this.reconnectAttempts = 0;
    this.currentSessionId = null;
    this.isManualDisconnect = false;

    this.messagesSignal.set([]);
    this.memoriesSignal.set([]);
    this.statusSignal.set(GraphSessionStatus.RUNNING);
    this.streamOpen.set(false);
    this.connectionStatusSignal.set('disconnected');
  }
}
