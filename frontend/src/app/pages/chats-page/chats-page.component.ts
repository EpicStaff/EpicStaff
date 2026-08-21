import { ChangeDetectionStrategy, Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { FullRealtimeConfigService } from '@shared/services';
import { finalize, forkJoin, Subject, takeUntil } from 'rxjs';

import { AgentDefinitionsApiService } from '../../features/agent-definitions/services/agent-definitions-api.service';
import { RealtimeAgentDefinitionsApiService } from '../../features/agent-definitions/services/realtime-agent-definitions-api.service';
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
        HideInlineSubtitleOnOverflowDirective,
    ],
    templateUrl: './chats-page.component.html',
    styleUrls: ['./chats-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsPageComponent implements OnInit, OnDestroy {
    private readonly chatsService = inject(ChatsService);
    private readonly agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private readonly realtimeApi = inject(RealtimeAgentDefinitionsApiService);
    private readonly fullRealtimeConfigService = inject(FullRealtimeConfigService);
    private readonly consoleService = inject(ConsoleService);

    public readonly agents = signal<ChatAgent[]>([]);
    public readonly isLoading = signal<boolean>(true);

    private destroy$ = new Subject<void>();

    ngOnInit(): void {
        this.loadAgentsData();
    }

    private loadAgentsData(): void {
        forkJoin({
            definitions: this.agentDefinitionsApi.getAgentDefinitions(),
            realtimeDefs: this.realtimeApi.list(),
            realtimeConfigs: this.fullRealtimeConfigService.getFullRealtimeConfigs(),
        })
            .pipe(
                takeUntil(this.destroy$),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: ({ definitions, realtimeDefs }) => {
                    // Only definitions that can actually connect: a realtime row must
                    // exist AND carry a realtime_config.
                    const realtimeByDef = new Map(realtimeDefs.map((r) => [r.agent_definition, r]));
                    const agents: ChatAgent[] = definitions
                        .map((agent) => {
                            const realtime = realtimeByDef.get(agent.id);
                            return realtime && realtime.realtime_config != null ? { agent, realtime } : null;
                        })
                        .filter((x): x is ChatAgent => x !== null);

                    this.agents.set(agents);
                    this.chatsService.setSelectedChatAgent(agents.length > 0 ? agents[0] : null);
                },
                error: (error) => {
                    console.error('Error loading agents data:', error);
                    this.isLoading.set(false);
                },
            });
    }

    onAgentUpdated(updated: ChatAgent): void {
        this.agents.update((list) => list.map((a) => (sameChatAgent(a, updated) ? updated : a)));
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
