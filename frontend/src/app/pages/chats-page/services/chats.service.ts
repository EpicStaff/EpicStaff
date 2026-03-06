import { Injectable, signal, computed } from '@angular/core';
import { FullAgent } from '../../../features/staff/services/full-agent.service';

@Injectable({
  providedIn: 'root',
})
export class ChatsService {
  private selectedAgent = signal<FullAgent | null>(null);

  // Computed signals
  readonly selectedAgentId$ = computed(() => this.selectedAgent()?.id || null);
  readonly selectedAgent$ = computed(() => this.selectedAgent());

  public setSelectedAgent(agent: FullAgent): void {
    this.selectedAgent.set(agent);
  }
}
