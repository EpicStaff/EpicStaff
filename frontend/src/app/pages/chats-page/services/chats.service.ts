import { computed, inject, Injectable, signal } from '@angular/core';
import { FullRealtimeConfigService } from '@shared/services';

import {
    ChatAgent,
    ChatAgentKind,
    chatAgentRealtimeConfigId,
    chatAgentTitle,
    ChatAgentVM,
} from '../models/chat-agent.model';

@Injectable({
    providedIn: 'root',
})
export class ChatsService {
    private readonly fullRealtimeConfigService = inject(FullRealtimeConfigService);

    private selectedChatAgent = signal<ChatAgent | null>(null);

    readonly activeTab = signal<ChatAgentKind>('staff');

    readonly selectedChatAgent$ = computed(() => this.selectedChatAgent());

    readonly selectedAgentVM$ = computed<ChatAgentVM | null>(() => {
        const sel = this.selectedChatAgent();
        if (!sel) return null;

        const realtimeConfigId = chatAgentRealtimeConfigId(sel);
        let modelName: string | null = null;
        let customName: string | null = null;

        if (sel.kind === 'staff') {
            const rt = sel.agent.realtime_agent;
            const slot = rt?.openai_config ?? rt?.elevenlabs_config ?? rt?.gemini_config ?? null;
            if (slot != null && typeof slot === 'object') {
                modelName = slot.model_name ?? null;
                customName = slot.custom_name ?? null;
            }
        } else if (realtimeConfigId != null) {
            const full =
                this.fullRealtimeConfigService.fullRealtimeConfigs().find((c) => c.id === realtimeConfigId) ?? null;
            modelName = full?.modelDetails?.name ?? null;
            customName = full?.custom_name ?? null;
        }

        return {
            kind: sel.kind,
            id: sel.agent.id,
            title: chatAgentTitle(sel),
            realtimeConfigId,
            modelName,
            customName,
        };
    });

    setSelectedChatAgent(agent: ChatAgent | null): void {
        this.selectedChatAgent.set(agent);
    }

    setActiveTab(tab: ChatAgentKind): void {
        this.activeTab.set(tab);
    }
}
