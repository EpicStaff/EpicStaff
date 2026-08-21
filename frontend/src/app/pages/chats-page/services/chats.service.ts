import { computed, inject, Injectable, signal } from '@angular/core';
import { FullRealtimeConfigService } from '@shared/services';

import {
    ChatAgent,
    chatAgentRealtimeConfigId,
    chatAgentTitle,
    chatAgentTranscriptionConfigId,
    ChatAgentVM,
} from '../models/chat-agent.model';

@Injectable({
    providedIn: 'root',
})
export class ChatsService {
    private readonly fullRealtimeConfigService = inject(FullRealtimeConfigService);

    private selectedChatAgent = signal<ChatAgent | null>(null);

    readonly selectedChatAgent$ = computed(() => this.selectedChatAgent());

    // Display projection. Resolves realtime model name/custom name from the reactive
    // realtime-config store, so it updates if configs load after selection.
    readonly selectedAgentVM$ = computed<ChatAgentVM | null>(() => {
        const sel = this.selectedChatAgent();
        if (!sel) return null;
        const realtimeConfigId = chatAgentRealtimeConfigId(sel);
        const full =
            realtimeConfigId != null
                ? (this.fullRealtimeConfigService.fullRealtimeConfigs().find((c) => c.id === realtimeConfigId) ?? null)
                : null;
        return {
            id: sel.agent.id,
            title: chatAgentTitle(sel),
            realtimeConfigId,
            transcriptionConfigId: chatAgentTranscriptionConfigId(sel),
            modelName: full?.modelDetails?.name ?? null,
            customName: full?.custom_name ?? null,
        };
    });

    setSelectedChatAgent(agent: ChatAgent | null): void {
        this.selectedChatAgent.set(agent);
    }
}
