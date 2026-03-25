import { Injectable, signal, inject } from '@angular/core';
import { Router } from '@angular/router';
import { FlowsApiService } from 'src/app/features/flows/services/flows-api.service';
import { ConfigService } from 'src/app/services/config/config.service';
import { FlowUnsavedStateService } from 'src/app/pages/flows-page/services/flow-unsaved-state.service';
import {
    EP_CHAT_COMMANDS,
    EP_CHAT_EVENT_TYPES,
    EpChatCommand,
    EpChatCommandResult,
    EpChatEvent,
    EpicChatCreateAgentPayload,
    EpicChatSyncAgentsPayload,
} from './models/epic-chat-command.model';
import { environment } from 'src/environments/environment';

@Injectable({
    providedIn: 'root',
})
export class EpicChatService {
    private static readonly DOCK_STORAGE_KEY = 'epicchat_is_docked';

    private readonly epChatCommandSignal = signal<EpChatCommand | null>(null);
    private readonly isDockedSignal = signal(
        localStorage.getItem(EpicChatService.DOCK_STORAGE_KEY) === '1',
    );
    private readonly dockWidthSignal = signal(420);
    private readonly isChatOpenSignal = signal(true);

    public readonly epChatCommand = this.epChatCommandSignal.asReadonly();
    public readonly isDocked = this.isDockedSignal.asReadonly();
    public readonly dockWidth = this.dockWidthSignal.asReadonly();
    public readonly isChatOpen = this.isChatOpenSignal.asReadonly();

    private readonly configService = inject(ConfigService);

    constructor(
        private readonly router: Router,
        private readonly flowUnsavedStateService: FlowUnsavedStateService,
        private readonly flowsApiService: FlowsApiService,
    ) {}

    public requestCreateAgent(payload: EpicChatCreateAgentPayload): void {
        this.epChatCommandSignal.set({
            requestId: this.generateRequestId(),
            action: EP_CHAT_COMMANDS.AGENT_CREATE,
            payload,
        });
    }

    public requestRemoveAgent(flowId: number | string): void {
        this.epChatCommandSignal.set({
            requestId: this.generateRequestId(),
            action: EP_CHAT_COMMANDS.AGENT_REMOVE,
            payload: { flowId },
        });
    }

    public onEpChatCommandResult(event: Event): void {
        const result = (event as CustomEvent<EpChatCommandResult>).detail;
        if (!result) {
            return;
        }
        if (!result.success) {
            console.error(
                `[EpicChat command failed] ${result.action}, requestId=${result.requestId}: ${result.message || 'Unknown error'}`,
            );
            return;
        }
        console.log(
            `[EpicChat command success] ${result.action}, requestId=${result.requestId}`,
        );
    }

    public onEpChatEvent(event: Event): void {
        const data = (event as CustomEvent<EpChatEvent>).detail;
        if (!data) {
            return;
        }
        if (data.type === 'agents.changed') {
            return;
        }
        switch (data.type) {
            case EP_CHAT_EVENT_TYPES.CHAT_CLOSED: {
                this.isChatOpenSignal.set(false);
                return;
            }
            case EP_CHAT_EVENT_TYPES.CHAT_OPENED: {
                this.isChatOpenSignal.set(true);
                return;
            }
            case EP_CHAT_EVENT_TYPES.APP_OPEN_FLOW: {
                const flowId = this.toNumber(data.payload?.['flowId']);
                if (flowId != null) {
                    this.router.navigate(['flows', flowId]);
                }
                return;
            }
            case EP_CHAT_EVENT_TYPES.APP_OPEN_NODE: {
                const flowId = this.toNumber(data.payload?.['flowId']);
                const nodeId =
                    data.payload?.['nodeId'] != null
                        ? String(data.payload['nodeId'])
                        : null;
                if (flowId != null) {
                    this.router.navigate(
                        ['flows', flowId],
                        nodeId ? { queryParams: { nodeId } } : {},
                    );
                }
                return;
            }
            case EP_CHAT_EVENT_TYPES.APP_REFRESH_CACHE: {
                this.flowUnsavedStateService
                    .confirmAndRefreshFlow()
                    .subscribe();
                return;
            }
            case EP_CHAT_EVENT_TYPES.APP_TOGGLE_DOCK: {
                this.toggleDock();
                return;
            }
            case EP_CHAT_EVENT_TYPES.AGENT_DISCONNECTED: {
                const flowId = this.toNumber(data.payload?.['flowId']);
                if (flowId != null) {
                    this.flowsApiService
                        .patchGraph(flowId, { epicchat_enabled: false })
                        .subscribe({
                            error: (err) =>
                                console.error(
                                    '[EpicChat] Failed to disable epicchat_enabled:',
                                    err,
                                ),
                        });
                }
                return;
            }
            default:
                console.log('[EpicChat event]', data.type, data.payload || {});
        }
    }

    public toggleDock(): void {
        this.isDockedSignal.update((v) => !v);
        localStorage.setItem(EpicChatService.DOCK_STORAGE_KEY, this.isDockedSignal() ? '1' : '0');
    }

    public setDockWidth(width: number): void {
        const minWidth = 320;
        const maxWidth = Math.max(
            minWidth,
            Math.floor(window.innerWidth * 0.7),
        );
        const next = Math.min(maxWidth, Math.max(minWidth, Math.round(width)));
        this.dockWidthSignal.set(next);
    }

    public dockLeftPx(): number {
        return 60;
    }

    private toNumber(v: unknown): number | null {
        if (v == null || v === '') return null;
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    }

    public toggleChat(host: HTMLElement | null | undefined): void {
        if (!host) {
            return;
        }
        const epicChatElement = host as {
            toggleChat?: () => void;
            shadowRoot?: ShadowRoot | null;
            querySelector?: (selectors: string) => Element | null;
        };
        if (epicChatElement.toggleChat) {
            epicChatElement.toggleChat();
            return;
        }
        const root = epicChatElement.shadowRoot ?? epicChatElement;
        const toggleButton =
            root.querySelector?.('.ep-chat-toggle-button') ??
            root.querySelector?.('ep-chat-toggle-button');
        if (toggleButton instanceof HTMLElement) {
            toggleButton.click();
        }
    }

    public reconnectAgents(): void {
        // const flowUrl = `${window.location.origin}/api`;
        const flowUrl = this.normalizeApiUrl(environment.apiUrl);
        this.flowsApiService.getEpicChatEnabledFlows().subscribe({
            next: (flows) => {
                console.log(`[EpicChat] Syncing ${flows.length} agent(s)`);
                const payload: EpicChatSyncAgentsPayload = {
                    agents: flows.map((flow) => ({
                        name: flow.name?.trim() || `Flow ${flow.id}`,
                        description: flow.description?.trim(),
                        flowId: flow.id,
                        flowUrl,
                    })),
                };
                this.epChatCommandSignal.set({
                    requestId: this.generateRequestId(),
                    action: EP_CHAT_COMMANDS.AGENTS_SYNC,
                    payload,
                });
            },
            error: (err) =>
                console.error('[EpicChat] Failed to fetch epicchat-enabled flows:', err),
        });
    }

    private normalizeApiUrl(apiUrl: string): string {
        return (apiUrl || '').trim().replace(/\/+$/, '');
    }

    private generateRequestId(): string {
        return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    }
}
