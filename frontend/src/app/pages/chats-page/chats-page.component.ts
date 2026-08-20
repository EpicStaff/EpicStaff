import { ChangeDetectionStrategy, Component, computed, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { TabButtonComponent } from '@shared/components';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { FullRealtimeConfigService } from '@shared/services';
import { finalize, forkJoin, Subject, takeUntil } from 'rxjs';

import { AgentDefinitionsApiService } from '../../features/agent-definitions/services/agent-definitions-api.service';
import { RealtimeAgentDefinitionsApiService } from '../../features/agent-definitions/services/realtime-agent-definitions-api.service';
import { FullAgentService } from '../../features/staff/services/full-agent.service';
import { SpinnerComponent } from '../../shared/components/spinner/spinner.component';
import { ChatsContentComponent } from './components/chats-content/chats-content.component';
import { ChatsSidebarComponent } from './components/chats-sidebar/chats-sidebar.component';
import { ChatAgent, sameChatAgent } from './models/chat-agent.model';
import { ChatsService } from './services/chats.service';
import { ConsoleService } from './services/console.service';

@Component({
    selector: 'app-chats-page',
    standalone: true,
    imports: [
        ChatsSidebarComponent,
        ChatsContentComponent,
        SpinnerComponent,
        TabButtonComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    templateUrl: './chats-page.component.html',
    styleUrls: ['./chats-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsPageComponent implements OnInit, OnDestroy {
    private readonly chatsService = inject(ChatsService);
    private readonly fullAgentService = inject(FullAgentService);
    private readonly agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private readonly realtimeApi = inject(RealtimeAgentDefinitionsApiService);
    private readonly fullRealtimeConfigService = inject(FullRealtimeConfigService);
    private readonly consoleService = inject(ConsoleService);

    public readonly staffAgents = signal<ChatAgent[]>([]);
    public readonly definitionAgents = signal<ChatAgent[]>([]);
    public readonly isLoading = signal<boolean>(true);

    public readonly activeTab = this.chatsService.activeTab;
    public readonly visibleAgents = computed<ChatAgent[]>(() =>
        this.activeTab() === 'staff' ? this.staffAgents() : this.definitionAgents()
    );

    private destroy$ = new Subject<void>();

    ngOnInit(): void {
        this.loadAgentsData();
    }

    private loadAgentsData(): void {
        forkJoin({
            fullAgents: this.fullAgentService.getFullAgents(),
            definitions: this.agentDefinitionsApi.getAgentDefinitions(),
            realtimeDefs: this.realtimeApi.list(),
            realtimeConfigs: this.fullRealtimeConfigService.getFullRealtimeConfigs(),
        })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: ({ fullAgents, definitions, realtimeDefs }) => {
                    const staff: ChatAgent[] = fullAgents.map((agent) => ({ kind: 'staff', agent }));

                    const realtimeByDef = new Map(realtimeDefs.map((r) => [r.agent_definition, r]));
                    const defs: ChatAgent[] = definitions
                        .map((agent) => {
                            const realtime = realtimeByDef.get(agent.id);
                            return realtime &&
                                (realtime.openai_config != null ||
                                    realtime.elevenlabs_config != null ||
                                    realtime.gemini_config != null)
                                ? ({ kind: 'definition', agent, realtime } as ChatAgent)
                                : null;
                        })
                        .filter((x): x is ChatAgent => x !== null);

                    this.staffAgents.set(staff);
                    this.definitionAgents.set(defs);

                    this.selectFirstOfActiveTab();
                },
                error: (error) => {
                    console.error('Error loading agents data:', error);
                    this.isLoading.set(false);
                },
            });
    }

    private selectFirstOfActiveTab(): void {
        const list = this.activeTab() === 'staff' ? this.staffAgents() : this.definitionAgents();
        this.chatsService.setSelectedChatAgent(list.length > 0 ? list[0] : null);
    }

    onTabChange(tab: 'staff' | 'definition'): void {
        if (this.activeTab() === tab) return;
        this.chatsService.setActiveTab(tab);
        if (this.consoleService.isConversationConnected()) {
            this.consoleService.disconnectConversation();
        }
        this.selectFirstOfActiveTab();
    }

    onAgentUpdated(updated: ChatAgent): void {
        const target = updated.kind === 'staff' ? this.staffAgents : this.definitionAgents;
        target.update((list) => list.map((a) => (sameChatAgent(a, updated) ? updated : a)));
        if (sameChatAgent(this.chatsService.selectedChatAgent$(), updated)) {
            this.chatsService.setSelectedChatAgent(updated);
        }
    }

    ngOnDestroy() {
        this.consoleService.disconnectConversation();
        this.destroy$.next();
        this.destroy$.complete();
    }
}
