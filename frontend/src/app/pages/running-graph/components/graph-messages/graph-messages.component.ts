import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    effect,
    ElementRef,
    EventEmitter,
    HostListener,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    QueryList,
    SimpleChanges,
    ViewChild,
    ViewChildren,
} from '@angular/core';
import { MarkdownModule } from 'ngx-markdown';
import { forkJoin, Observable, of, Subject } from 'rxjs';
import { exhaustMap, map, takeUntil } from 'rxjs/operators';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import {
    GraphSession,
    GraphSessionService,
    GraphSessionStatus,
    SessionUpdates,
} from '../../../../features/flows/services/flows-sessions.service';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';
import { GetAgentRequest } from '../../../../features/staff/models/agent.model';
import { AgentsService } from '../../../../features/staff/services/staff.service';
import { GetTaskRequest } from '../../../../features/tasks/models/task.model';
import { TasksService } from '../../../../features/tasks/services/tasks.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CodeAgentStreamMessageData, GraphMessage, MessageType } from '../../models/graph-session-message.model';
import { SessionStatusMessageData } from '../../models/update-session-status.model';
import { AnswerToLLMService } from '../../services/answer-to-llm.service';
import { RunSessionSSEService } from '../../services/graph-session-sse.service';
import { RunGraphPageService } from '../../services/run-graph-page.service';
import { WarningMessagesComponent } from '../warning-messages/warning-messages.component';
import { AgentFinishMessageComponent } from './components/agent-finish/agent-finish.component';
import { AgentMessageComponent } from './components/agent-message/agent-message.component';
import { ClassificationDtMessageComponent } from './components/classification-dt-message/classification-dt-message.component';
import { CodeAgentStreamMessageComponent } from './components/code-agent-stream-message/code-agent-stream-message.component';
import { ErrorMessageComponent } from './components/error-message/error-message.component';
import { ExtractedChunksMessageComponent } from './components/extracted-chunks/extracted-chunks-message.component';
import { FinishMessageComponent } from './components/finish-message/finish-message.component';
import { LlmMessageComponent } from './components/llm-message/llm-message.component';
import { LoadingDotsComponent } from './components/loading-animation/loading-animation.component';
import { PythonMessageComponent } from './components/python-message/python-message.component';
import { StartMessageComponent } from './components/start-message/start-message.component';
import { SubgraphFinishMessageComponent } from './components/subgraph-finish-message/subgraph-finish-message.component';
import { SubgraphStartMessageComponent } from './components/subgraph-start-message/subgraph-start-message.component';
import { TaskMessageComponent } from './components/task-message/task-message.component';
import { ProjectTransitionComponent } from './components/transition/project-transition.component';
import { WaitForUserInputComponent } from './components/user-input-component/user-input-component.component';
import { UserMessageComponent } from './components/user-message/user-message.component';
import { isMessageType } from './helper_functions/message-helper';

interface MessageContext {
    key: string;
    index: number;
    depth: number;
    path: string[];
    isSubgraphStart: boolean;
    isSubgraphFinish: boolean;
}

// Message types that actually render a card in the template @switch.
// Anything else (update_session_status, graph_end, future stream types like
// python_stream, etc.) creates an empty .message div and breaks the unread
// counter, so we keep it out of visibleMessageEntries.
const RENDERABLE_MESSAGE_TYPES: ReadonlySet<string> = new Set([
    MessageType.START,
    MessageType.USER,
    MessageType.AGENT,
    MessageType.AGENT_FINISH,
    MessageType.PYTHON,
    MessageType.LLM,
    MessageType.EXTRACTED_CHUNKS,
    MessageType.ERROR,
    MessageType.TASK,
    MessageType.FINISH,
    MessageType.CODE_AGENT_STREAM,
    MessageType.SUBGRAPH_START,
    MessageType.SUBGRAPH_FINISH,
    MessageType.CONDITION_GROUP,
    MessageType.CONDITION_GROUP_MANIPULATION,
    MessageType.CLASSIFICATION_PROMPT,
]);

interface MessageViewEntry {
    key: string;
    message: GraphMessage;
    index: number;
    agent: GetAgentRequest | null;
    project: GetProjectRequest | null;
    subgraphName: string | null;
    hasNestedMessages: boolean;
    isNestedMessagesOpen: boolean;
    shouldShowTransition: boolean;
    rootKey: string | null;
    rootView: RootDrilldownView | null;
}

interface RootDrilldownView {
    rootKey: string;
    breadcrumbs: { key: string; label: string }[];
    filteredBreadcrumbs: { key: string; label: string; index: number }[];
    drilldownEntries: MessageViewEntry[];
    currentDrillEntry: MessageViewEntry | null;
    breadcrumbSearchTerm: string;
    breadcrumbSearchExpanded: boolean;
    hasBreadcrumbOverflow: boolean;
    isClosing: boolean;
}

const TERMINAL_STATUSES = new Set<GraphSessionStatus>([
    GraphSessionStatus.ENDED,
    GraphSessionStatus.ERROR,
    GraphSessionStatus.STOP,
    GraphSessionStatus.EXPIRED,
]);

@Component({
    selector: 'app-graph-messages',
    standalone: true,
    imports: [
        CommonModule,
        MarkdownModule,
        LoadingDotsComponent,
        StartMessageComponent,
        AgentMessageComponent,
        FinishMessageComponent,
        TaskMessageComponent,
        PythonMessageComponent,
        LlmMessageComponent,
        AgentFinishMessageComponent,
        ErrorMessageComponent,
        ProjectTransitionComponent,
        WaitForUserInputComponent,
        UserMessageComponent,
        ExtractedChunksMessageComponent,
        ClassificationDtMessageComponent,
        WarningMessagesComponent,
        SubgraphStartMessageComponent,
        SubgraphFinishMessageComponent,
        CodeAgentStreamMessageComponent,
        AppSvgIconComponent,
    ],
    templateUrl: './graph-messages.component.html',
    styleUrls: ['./graph-messages.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [RunSessionSSEService],
})
export class GraphMessagesComponent implements OnInit, OnDestroy, OnChanges, AfterViewInit {
    @Input() graphId: number | null = null;
    @Input() sessionId: string | null = null;
    @Input() compact: boolean = false;
    @Output() sessionStatusChanged = new EventEmitter<GraphSessionStatus>();
    @Output() messagesChanged = new EventEmitter<GraphMessage[]>();

    // Data arrays and objects
    public agents: GetAgentRequest[] = [];
    public tasks: GetTaskRequest[] = [];
    public session: GraphSession | null = null;

    // Animation control for messages
    public animatedIndices: { [key: number]: boolean } = {};

    // Loading state
    private isLoading = true;

    public showUserInputWithDelay: boolean = false;

    // New property for storing update status data from messages
    public updateSessionStatusData: SessionStatusMessageData | null = null;
    public statusWaitForUser: boolean = false;

    // Warning messages
    public warningMessages: string[] | null = null;

    // Connection status
    public connectionStatus: 'connected' | 'connecting' | 'disconnected' | 'reconnecting' | 'manually_disconnected' =
        'disconnected';
    public reconnectAttempts: number = 0;
    public sseEnabled = false;

    // Lookup maps for quick reference
    private agentMap: Map<number, GetAgentRequest> = new Map();
    private taskMap: Map<number, GetTaskRequest> = new Map();

    public messages: GraphMessage[] = [];
    public visibleMessageEntries: MessageViewEntry[] = [];

    private readonly PAGE_SIZE = 20;
    private seenKeys = new Set<string>();
    private hasReconciledTerminal = false;
    private currentOffset = 0;
    public isLoadingMore = false;
    public hasMore = true;
    private loadingSubgraphIds = new Set<string>();
    private subgraphOffsets = new Map<string, number>();
    private subgraphHasMore = new Map<string, boolean>();

    private isFinishing = false;
    private finishTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly DRAIN_DELAY_MS = 3000;
    private drillPaths = new Map<string, string[]>();
    private breadcrumbsByRoot = new Map<string, { key: string; label: string }[]>();
    private filteredBreadcrumbsByRoot = new Map<string, { key: string; label: string; index: number }[]>();
    private drilldownEntriesByRoot = new Map<string, MessageViewEntry[]>();
    private currentDrillEntryByRoot = new Map<string, MessageViewEntry | null>();
    private closingRootKeys = new Set<string>();
    private readonly drilldownCloseDelayMs = 220;
    private breadcrumbSearchByRoot = new Map<string, string>();
    private breadcrumbSearchExpandedByRoot = new Map<string, boolean>();
    private breadcrumbOverflowByRoot = new Map<string, boolean>();
    private breadcrumbOverflowRefreshId: number | null = null;

    private messageContexts: MessageContext[] = [];
    private messageContextByKey = new Map<string, MessageContext>();
    private messageByKey = new Map<string, GraphMessage>();
    private messageGraphIdByKey = new Map<string, number>();
    private graphCache = new Map<number, GraphDto>();
    private graphNameById = new Map<number, string>();
    private graphLoadInFlight = new Set<number>();

    private destroy$ = new Subject<void>();

    @ViewChild('messagesContainer')
    private messagesContainer!: ElementRef<HTMLElement>;

    @ViewChildren('breadcrumbsScroller')
    private breadcrumbScrollers!: QueryList<ElementRef<HTMLElement>>;

    public showScrollToTop = false;
    public showScrollToBottom = false;
    private autoScrollEnabled = true;
    private readonly scrollBottomThreshold = 80;
    public unseenMessageCount = 0;
    private seenMessageCount = 0;
    private lastScrollTop = 0;

    constructor(
        public sseService: RunSessionSSEService,
        private agentsService: AgentsService,
        private tasksService: TasksService,
        private cdr: ChangeDetectorRef,
        private answerToLLMService: AnswerToLLMService,
        private runGraphPageService: RunGraphPageService,
        private flowService: FlowsApiService,
        private graphSessionService: GraphSessionService
    ) {
        effect(() => {
            const sseMessages = this.sseService.messages();
            this.mergeMessages(sseMessages);
            this.messagesChanged.emit(this.messages);
            this.rebuildMessageState(this.messages);
            this.processMessages();
            this.checkIfFinish();
            this.cdr.markForCheck();

            if (this.autoScrollEnabled) {
                this.unseenMessageCount = 0;
                if (this.messages.length > 0) {
                    requestAnimationFrame(() => this.scrollToBottom());
                }
            } else {
                this.unseenMessageCount = Math.max(0, this.messages.length - this.seenMessageCount);
            }
        });

        effect(() => {
            const status = this.sseService.status();
            this.sessionStatusChanged.emit(status);
            this.statusWaitForUser = status === GraphSessionStatus.WAITING_FOR_USER;
            this.showUserInputWithDelay = this.statusWaitForUser;
            this.checkIfFinish();
            // Bugfix: when the run reaches a terminal status, reconcile the full message list
            // from the server so any messages the realtime SSE stream missed are backfilled (once).
            if (TERMINAL_STATUSES.has(status) && !this.hasReconciledTerminal) {
                this.hasReconciledTerminal = true;
                this.reconcileMessagesFromServer();
            }
            this.cdr.markForCheck();
        });

        effect(() => {
            const memories = this.sseService.memories();
            this.runGraphPageService.setMemories(memories);
        });

        effect(() => {
            const connectionStatus = this.sseService.connectionStatus();
            this.connectionStatus = connectionStatus;
            this.cdr.markForCheck();
        });
    }

    get isProcessing(): boolean {
        const status = this.sseService.status();
        const isTerminalStatus =
            status === GraphSessionStatus.ERROR ||
            status === GraphSessionStatus.STOP ||
            status === GraphSessionStatus.ENDED ||
            status === GraphSessionStatus.EXPIRED;

        if (isTerminalStatus) {
            return false;
        }

        return this.isLoading || this.sseService.isStreaming();
    }

    public ngOnInit(): void {
        this.loadData();
    }

    public ngAfterViewInit(): void {
        this.scheduleBreadcrumbOverflowRefresh();
        this.breadcrumbScrollers.changes
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => this.scheduleBreadcrumbOverflowRefresh());
    }

    public onMessagesScroll(): void {
        const el = this.messagesContainer?.nativeElement;
        if (!el) return;

        const scrollTop = el.scrollTop;
        const distanceFromBottom = el.scrollHeight - scrollTop - el.clientHeight;
        const isAtBottom = distanceFromBottom <= this.scrollBottomThreshold;
        const scrolledUp = scrollTop < this.lastScrollTop;
        this.lastScrollTop = scrollTop;

        if (scrolledUp && this.autoScrollEnabled) {
            this.autoScrollEnabled = false;
            this.seenMessageCount = this.visibleMessageEntries.length;
        }

        if (!this.autoScrollEnabled && isAtBottom) {
            this.autoScrollEnabled = true;
            this.unseenMessageCount = 0;
        } else if (!this.autoScrollEnabled) {
            this.updateSeenFromScrollPosition();
        }

        if (distanceFromBottom < 200 && this.hasMore && !this.isLoadingMore) {
            this.loadMoreMessages();
        }

        if (distanceFromBottom < 200) {
            this.drillPaths.forEach((path, rootKey) => {
                const currentKey = path[path.length - 1] ?? rootKey;
                const message = this.messageByKey.get(currentKey);
                const execId = (message?.message_data as unknown as Record<string, unknown>)?.[
                    'subgraph_execution_id'
                ] as string | undefined;
                if (execId && this.subgraphHasMore.get(execId) && !this.loadingSubgraphIds.has(execId)) {
                    this.loadMoreSubgraphPage(execId);
                }
            });
        }

        this.updateScrollButtonsVisibility();

        this.cdr.markForCheck();
    }

    private updateSeenFromScrollPosition(): void {
        const el = this.messagesContainer?.nativeElement;
        if (!el) return;

        const viewportBottom = el.getBoundingClientRect().bottom;
        const messageElements = el.querySelectorAll<HTMLElement>('.messages-list > .message');

        let visibleCount = 0;
        for (let i = 0; i < messageElements.length; i++) {
            const rect = messageElements[i].getBoundingClientRect();
            const midpoint = rect.top + rect.height / 2;
            if (midpoint <= viewportBottom) {
                visibleCount = i + 1;
            } else {
                break;
            }
        }

        if (visibleCount > this.seenMessageCount) {
            const prevSeen = this.seenMessageCount;
            const prevUnseen = this.unseenMessageCount;
            const newlySeenEntries = this.visibleMessageEntries.slice(prevSeen, visibleCount);
            this.seenMessageCount = visibleCount;
            this.unseenMessageCount = Math.max(0, this.visibleMessageEntries.length - this.seenMessageCount);
            const delta = prevUnseen - this.unseenMessageCount;
            console.log(
                `[unread] -${delta} (${prevUnseen} → ${this.unseenMessageCount}); read ${newlySeenEntries.length} message(s):`,
                newlySeenEntries.map((entry) => ({
                    index: entry.index,
                    type: entry.message.message_data?.message_type,
                    name: entry.message.name,
                    key: entry.key,
                }))
            );
        }
    }

    public scrollToTop(): void {
        const el = this.messagesContainer?.nativeElement;
        if (!el) return;
        if (this.autoScrollEnabled) {
            this.autoScrollEnabled = false;
            this.seenMessageCount = this.visibleMessageEntries.length;
        }
        this.updateScrollButtonsVisibility();
        this.cdr.markForCheck();
        el.scrollTo({ top: 0, behavior: 'smooth' });
    }

    private scrollToBottom(): void {
        const el = this.messagesContainer?.nativeElement;
        if (!el) return;
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }

    private updateScrollButtonsVisibility(): void {
        const el = this.messagesContainer?.nativeElement;
        if (!el) return;
        const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        this.showScrollToTop = el.scrollTop > 150;
        this.showScrollToBottom = !this.autoScrollEnabled && distanceFromBottom > this.scrollBottomThreshold;
    }

    public scrollToBottomAndReengage(): void {
        this.autoScrollEnabled = true;
        this.unseenMessageCount = 0;
        this.scrollToBottom();
    }

    public ngOnDestroy(): void {
        this.sseService.stopStream();
        if (this.finishTimer !== null) {
            clearTimeout(this.finishTimer);
            this.finishTimer = null;
        }
        this.destroy$.next();
        this.destroy$.complete();
        if (this.breadcrumbOverflowRefreshId !== null) {
            window.clearTimeout(this.breadcrumbOverflowRefreshId);
            this.breadcrumbOverflowRefreshId = null;
        }
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['sessionId'] && !changes['sessionId'].firstChange) {
            this.destroy$.next();
            this.sseService.stopStream();
            if (this.finishTimer !== null) {
                clearTimeout(this.finishTimer);
                this.finishTimer = null;
            }
            this.isLoading = true;
            this.sseEnabled = false;
            this.session = null;
            this.animatedIndices = {};
            this.updateSessionStatusData = null;
            this.statusWaitForUser = false;
            this.isFinishing = false;
            this.showUserInputWithDelay = false;
            this.warningMessages = null;
            this.autoScrollEnabled = true;
            this.lastScrollTop = 0;
            this.showScrollToTop = false;
            this.showScrollToBottom = false;
            this.unseenMessageCount = 0;
            this.seenMessageCount = 0;
            this.messages = [];
            this.visibleMessageEntries = [];
            this.seenKeys = new Set<string>();
            this.hasReconciledTerminal = false;
            this.currentOffset = 0;
            this.isLoadingMore = false;
            this.hasMore = true;
            this.loadingSubgraphIds = new Set<string>();
            this.subgraphOffsets = new Map<string, number>();
            this.subgraphHasMore = new Map<string, boolean>();
            this.drillPaths.clear();
            this.breadcrumbsByRoot.clear();
            this.filteredBreadcrumbsByRoot.clear();
            this.drilldownEntriesByRoot.clear();
            this.currentDrillEntryByRoot.clear();
            this.breadcrumbSearchByRoot.clear();
            this.breadcrumbSearchExpandedByRoot.clear();
            this.breadcrumbOverflowByRoot.clear();
            this.messageContexts = [];
            this.messageContextByKey.clear();
            this.messageByKey.clear();
            this.messageGraphIdByKey.clear();
            this.graphCache.clear();
            this.graphNameById.clear();
            this.graphLoadInFlight.clear();
            this.cdr.markForCheck();

            if (this.sessionId) {
                this.loadData();
            }
        }
    }

    private loadData(): void {
        const graphId = this.graphId;
        if (!this.sessionId || graphId == null || !isFinite(graphId)) return;

        this.graphSessionService
            .getSessionById(+this.sessionId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (session) => {
                    if (!TERMINAL_STATUSES.has(session.status)) {
                        this.sseEnabled = true;
                        this.sseService.startStream(this.sessionId!);
                    } else {
                        this.sseService.setStatus(session.status);
                    }
                    this.loadMoreMessages();
                },
                error: () => {
                    this.sseEnabled = true;
                    this.sseService.startStream(this.sessionId!);
                    this.loadMoreMessages();
                },
            });

        // Load warning messages
        this.graphSessionService
            .getSessionWarnings(this.sessionId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.warningMessages = response?.messages ?? null;
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    console.error('Failed to load warnings:', err);
                    this.warningMessages = null;
                },
            });

        this.flowService
            .getGraphById(graphId)
            .pipe(
                takeUntil(this.destroy$),
                exhaustMap((graph) => {
                    this.graphCache.set(graph.id, graph);
                    const agentsIDs = new Set(graph.crew_node_list.flatMap((node) => node.crew.agents));
                    const tasksIDs = new Set(graph.crew_node_list.flatMap((node) => node.crew.tasks));

                    return forkJoin({
                        agents: this.fetchAndMapById(
                            agentsIDs,
                            this.agentsService.getAgentById.bind(this.agentsService),
                            this.agentMap
                        ),
                        tasks: this.fetchAndMapById(
                            tasksIDs,
                            this.tasksService.getTaskById.bind(this.tasksService),
                            this.taskMap
                        ),
                        graphsLight: this.flowService.getGraphsLight(),
                    });
                })
            )
            .subscribe({
                next: ({ agents, tasks, graphsLight }) => {
                    this.agents = agents;
                    this.tasks = tasks;
                    this.graphNameById = new Map(graphsLight.map((graph) => [graph.id, graph.name]));
                    if (this.graphId && this.graphCache.has(this.graphId)) {
                        const rootGraph = this.graphCache.get(this.graphId);
                        if (rootGraph) {
                            this.graphNameById.set(rootGraph.id, rootGraph.name);
                        }
                    }
                    this.rebuildMessageState(this.messages);
                    this.isLoading = false;
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    console.error('Failed to load data:', err);
                    this.isLoading = false;
                    this.cdr.markForCheck();
                },
            });
    }

    private fetchAndMapById<T>(
        ids: Set<number>,
        fetchFn: (id: number) => Observable<T>,
        mapToUpdate: Map<number, T>
    ): Observable<T[]> {
        if ([...ids].length === 0) return of([]);
        return forkJoin(
            [...ids].map((id) =>
                fetchFn(id).pipe(
                    map((result) => {
                        mapToUpdate.set(id, result);
                        return result;
                    })
                )
            )
        );
    }

    private processMessages(): void {
        const messages = this.sseService.messages();
        if (messages.length > 0) {
            const lastMessage: GraphMessage = messages[messages.length - 1];

            if (lastMessage.message_data && lastMessage.message_data.message_type === 'update_session_status') {
                // Cast the message_data to SessionStatusMessageData interface
                this.updateSessionStatusData = lastMessage.message_data as SessionStatusMessageData;

                // Check if status is "wait_for_user" and update statusWaitForUser flag
                if (this.updateSessionStatusData.status === 'wait_for_user') {
                    this.statusWaitForUser = true;

                    // For initial load, show input immediately
                    if (this.isLoading) {
                        this.showUserInputWithDelay = true;
                    }
                } else {
                    this.statusWaitForUser = false;
                    this.showUserInputWithDelay = false;
                }
            } else {
                this.updateSessionStatusData = null;
                this.statusWaitForUser = false;
                this.showUserInputWithDelay = false;
            }
        }
    }

    public getSubgraphName(message: GraphMessage): string | null {
        const key = this.getMessageKey(message);
        const parentGraphId = this.messageGraphIdByKey.get(key);
        if (!parentGraphId) return null;
        const subgraphId = this.getSubgraphIdForNode(parentGraphId, message.name);
        if (!subgraphId) return null;
        return this.graphNameById.get(subgraphId) ?? null;
    }

    private buildMessageGraphContexts(messages: GraphMessage[]): void {
        this.messageGraphIdByKey.clear();
        const graphId = this.graphId;
        if (graphId == null || !isFinite(graphId)) return;
        const graphStack: number[] = [graphId];

        messages.forEach((message) => {
            const key = this.getMessageKey(message);
            const currentGraphId = graphStack[graphStack.length - 1];
            this.messageGraphIdByKey.set(key, currentGraphId);

            const isSubgraphStart = isMessageType(message, MessageType.SUBGRAPH_START);
            const isSubgraphFinish = isMessageType(message, MessageType.SUBGRAPH_FINISH);

            if (isSubgraphStart) {
                const subgraphId = this.getSubgraphIdForNode(currentGraphId, message.name);
                if (subgraphId) {
                    this.ensureGraphLoaded(subgraphId);
                    graphStack.push(subgraphId);
                }
            } else if (isSubgraphFinish && graphStack.length > 1) {
                graphStack.pop();
            }
        });
    }

    private getSubgraphIdForNode(graphId: number, nodeName: string): number | null {
        const graph = this.graphCache.get(graphId);
        if (!graph?.subgraph_node_list?.length) return null;
        const match = graph.subgraph_node_list.find((node) => node.node_name === nodeName);
        return match?.subgraph ?? null;
    }

    private ensureGraphLoaded(graphId: number): void {
        if (this.graphCache.has(graphId) || this.graphLoadInFlight.has(graphId)) {
            return;
        }
        this.graphLoadInFlight.add(graphId);
        this.flowService
            .getGraphById(graphId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (graph) => {
                    this.graphCache.set(graph.id, graph);
                    this.graphLoadInFlight.delete(graphId);
                    this.rebuildMessageState(this.messages);
                    this.cdr.markForCheck();
                },
                error: (err) => {
                    console.error('Failed to load subgraph:', err);
                    this.graphLoadInFlight.delete(graphId);
                },
            });
    }

    // UPD (EST-904 Mark message final in session)
    // Stop session only after message with type 'graph_end'
    private checkIfFinish() {
        const messages = this.sseService.messages();
        if (messages.length > 0) {
            const lastMessage: GraphMessage = messages[messages.length - 1];
            const lastTime = lastMessage.created_at;
            const sameTimeMessages = messages.filter((msg) => msg.created_at === lastTime);
            const sessionStatus = this.sseService.status();

            // Check for graph_end message - marks the session as finished
            if (sameTimeMessages.some((msg) => msg.message_data.message_type === MessageType.GRAPH_END)) {
                if (this.isFinishing) return;
                this.isFinishing = true;
                // graph_end authoritatively ends the session — flip the badge immediately.
                // The SSE service will block any late status: run from overwriting it.
                this.sseService.setStatus(GraphSessionStatus.ENDED);
                // Short drain — keep the stream open to catch any late messages,
                // then stop it and refine the final status once (ENDED/ERROR/STOP/...).
                this.finishTimer = setTimeout(() => {
                    this.finishTimer = null;
                    this.sseService.stopStream();
                    this.updateSessionStatus();
                }, this.DRAIN_DELAY_MS);
                return;
            }

            if (
                sameTimeMessages.some(
                    (msg) =>
                        msg.message_data.message_type === 'update_session_status' &&
                        msg.message_data.status === GraphSessionStatus.WAITING_FOR_USER
                ) &&
                sessionStatus === GraphSessionStatus.WAITING_FOR_USER
            ) {
                this.sseService.stopStream();
                this.updateSessionStatus();
            }
        }
    }

    private updateSessionStatus(): void {
        const currentSessionId = this.sessionId;
        this.graphSessionService
            .getSessionUpdates(this.sessionId!)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: ({ status }: SessionUpdates) => {
                    if (this.sessionId !== currentSessionId) return;
                    // Refine the final status. The lock in the SSE service allows
                    // transitions between terminal statuses (ENDED → ERROR/STOP)
                    // but blocks downgrades back to run.
                    this.sseService.setStatus(status);
                },
                error: (err) => console.error(err),
            });
    }

    public getAgentFromMessage(message: GraphMessage): GetAgentRequest | null {
        if (!message.message_data) return null;

        if (
            (message.message_data.message_type === 'agent' || message.message_data.message_type === 'agent_finish') &&
            'agent_id' in message.message_data
        ) {
            const agentId = message.message_data.agent_id;
            return this.agentMap.get(agentId) || null;
        }

        return null;
    }

    public getProjectFromMessage(message: GraphMessage): GetProjectRequest | null {
        if (!message) return null;

        if (message.name) {
            return { name: message.name } as GetProjectRequest;
        }

        return null;
    }

    // Check if we should show transition between sessions
    public shouldShowTransition(currentMessage: GraphMessage, index: number): boolean {
        // Don't show transition for the first message
        if (index === 0) return false;

        const prevMessage = this.messages[index - 1];

        // If current message is 'start' and previous is 'finish', show transition
        return isMessageType(currentMessage, MessageType.START) && isMessageType(prevMessage, MessageType.FINISH);
    }

    public isIndideSubFlow(message: GraphMessage): boolean {
        return (
            isMessageType(message, MessageType.SUBGRAPH_START) || isMessageType(message, MessageType.SUBGRAPH_FINISH)
        );
    }

    public onViewNestedMessages(message: GraphMessage): void {
        if (!this.sseEnabled) {
            const subgraphExecutionId = (message.message_data as unknown as Record<string, unknown>)[
                'subgraph_execution_id'
            ] as string | undefined;
            if (subgraphExecutionId) {
                this.loadSubgraphMessages(subgraphExecutionId, 0);
            }
        }

        const context = this.getMessageContext(message);
        if (!context || !context.isSubgraphStart) return;
        const rootKey = this.getRootKeyForContext(context);
        if (!rootKey) return;
        const nextPath = [...context.path, context.key];
        const currentPath = this.drillPaths.get(rootKey);
        if (currentPath && this.pathsEqual(currentPath, nextPath)) {
            this.closingRootKeys.add(rootKey);
            this.cdr.markForCheck();
            setTimeout(() => {
                this.drillPaths.delete(rootKey);
                this.closingRootKeys.delete(rootKey);
                this.updateDrilldownView();
                this.cdr.markForCheck();
                // Drilldown removed → content height shrank. The container
                // doesn't fire a scroll event on shrink, so recompute manually.
                this.refreshScrollButtonsAfterRender();
            }, this.drilldownCloseDelayMs);
        } else {
            this.closingRootKeys.delete(rootKey);
            this.drillPaths.set(rootKey, nextPath);
        }
        this.updateDrilldownView();
        this.refreshScrollButtonsAfterRender();
    }

    public onBreadcrumbClick(rootKey: string, index: number): void {
        const currentPath = this.drillPaths.get(rootKey);
        if (!currentPath) return;
        this.drillPaths.set(rootKey, currentPath.slice(0, index + 1));
        this.updateDrilldownView();
        this.refreshScrollButtonsAfterRender();
    }

    private refreshScrollButtonsAfterRender(): void {
        requestAnimationFrame(() => {
            this.updateScrollButtonsVisibility();
            this.cdr.markForCheck();
        });
    }

    public isDrilldownRoot(message: GraphMessage): boolean {
        const context = this.getMessageContext(message);
        return !!context && context.isSubgraphStart && context.path.length === 0 && this.drillPaths.has(context.key);
    }

    public isDrilldownClosing(message: GraphMessage): boolean {
        const rootKey = this.getRootKeyForMessage(message);
        if (!rootKey) return false;
        return this.closingRootKeys.has(rootKey);
    }

    public hasNestedMessages(message: GraphMessage): boolean {
        const context = this.getMessageContext(message);
        if (!context) return false;
        return this.hasNestedMessagesForContext(context);
    }

    public isNestedMessagesOpen(message: GraphMessage): boolean {
        const context = this.getMessageContext(message);
        if (!context) return false;
        return this.isNestedMessagesOpenForContext(context);
    }

    private hasNestedMessagesForContext(context: MessageContext): boolean {
        if (!context.isSubgraphStart) return false;
        const nestedPath = [...context.path, context.key];
        return this.messageContexts.some((ctx) => this.pathsEqual(ctx.path, nestedPath));
    }

    private isNestedMessagesOpenForContext(context: MessageContext): boolean {
        if (!context.isSubgraphStart) return false;
        const rootKey = this.getRootKeyForContext(context);
        if (!rootKey) return false;
        if (this.closingRootKeys.has(rootKey)) return false;
        const currentPath = this.drillPaths.get(rootKey);
        if (!currentPath) return false;
        const targetPath = [...context.path, context.key];
        return this.pathsEqual(currentPath, targetPath);
    }

    public getBreadcrumbs(message: GraphMessage): { key: string; label: string }[] {
        const rootKey = this.getRootKeyForMessage(message);
        if (!rootKey) return [];
        return this.breadcrumbsByRoot.get(rootKey) ?? [];
    }

    public getFilteredBreadcrumbs(message: GraphMessage): { key: string; label: string; index: number }[] {
        const rootKey = this.getRootKeyForMessage(message);
        if (!rootKey) return [];
        return this.filteredBreadcrumbsByRoot.get(rootKey) ?? [];
    }

    public onBreadcrumbSearch(rootKey: string, value: string): void {
        const nextValue = value ?? '';
        if (nextValue.trim().length === 0) {
            this.breadcrumbSearchByRoot.delete(rootKey);
        } else {
            this.breadcrumbSearchByRoot.set(rootKey, nextValue);
        }
        this.updateFilteredBreadcrumbs(rootKey);
        this.updateRootViews();
        this.cdr.markForCheck();
        this.scheduleBreadcrumbOverflowRefresh();
    }

    public getBreadcrumbSearchTerm(rootKey: string): string {
        return this.breadcrumbSearchByRoot.get(rootKey) ?? '';
    }

    public isBreadcrumbSearchExpanded(rootKey: string): boolean {
        return this.breadcrumbSearchExpandedByRoot.get(rootKey) ?? false;
    }

    public toggleBreadcrumbSearch(rootKey: string): void {
        const nextValue = !this.isBreadcrumbSearchExpanded(rootKey);
        if (nextValue) {
            this.breadcrumbSearchExpandedByRoot.set(rootKey, true);
        } else {
            this.breadcrumbSearchExpandedByRoot.delete(rootKey);
            this.breadcrumbSearchByRoot.delete(rootKey);
        }
        this.updateFilteredBreadcrumbs(rootKey);
        this.updateRootViews();
        this.cdr.markForCheck();
        this.scheduleBreadcrumbOverflowRefresh();
    }

    public onBreadcrumbSearchBlur(rootKey: string): void {
        if (!this.getBreadcrumbSearchTerm(rootKey).trim()) {
            this.breadcrumbSearchExpandedByRoot.delete(rootKey);
            this.breadcrumbSearchByRoot.delete(rootKey);
            this.updateFilteredBreadcrumbs(rootKey);
            this.updateRootViews();
            this.cdr.markForCheck();
            this.scheduleBreadcrumbOverflowRefresh();
        }
    }

    public scrollBreadcrumbs(container: HTMLElement, direction: 'left' | 'right'): void {
        if (!container) return;
        const baseOffset = Math.max(container.clientWidth * 0.6, 140);
        const offset = direction === 'left' ? -baseOffset : baseOffset;
        container.scrollBy({ left: offset, behavior: 'smooth' });
    }

    public onBreadcrumbsScroll(rootKey: string, container: HTMLElement): void {
        this.updateBreadcrumbOverflow(rootKey, container);
    }

    public hasBreadcrumbOverflow(rootKey: string): boolean {
        return this.breadcrumbOverflowByRoot.get(rootKey) ?? false;
    }

    public getDrilldownEntries(message: GraphMessage): MessageViewEntry[] {
        const rootKey = this.getRootKeyForMessage(message);
        if (!rootKey) return [];
        return this.drilldownEntriesByRoot.get(rootKey) ?? [];
    }

    public getRootKeyForMessage(message: GraphMessage): string | null {
        const context = this.getMessageContext(message);
        if (!context) return null;
        return this.getRootKeyForContext(context);
    }

    public getCurrentDrillEntry(message: GraphMessage): MessageViewEntry | null {
        const rootKey = this.getRootKeyForMessage(message);
        if (!rootKey) return null;
        return this.currentDrillEntryByRoot.get(rootKey) ?? null;
    }

    public getBreadcrumbLabel(key: string): string {
        const message = this.messageByKey.get(key);
        return message?.name || 'Subgraph';
    }

    onUserMessageSubmitted(message: string) {
        // Make sure we have valid sessionId and updateSessionStatusData
        if (!this.sessionId) {
            console.warn('No sessionId available; cannot send answer.');
            return;
        }
        if (!this.updateSessionStatusData) {
            console.warn('No updateSessionStatusData available; cannot send answer.');
            return;
        }

        const requestData = {
            session_id: +this.sessionId,
            crew_id: this.updateSessionStatusData.crew_id,
            execution_order: this.updateSessionStatusData.status_data.execution_order,
            name: this.updateSessionStatusData.status_data.name,
            answer: message,
        };

        this.answerToLLMService.sendAnswerToLLM(requestData).subscribe({
            next: (response) => {
                console.log('Answer to LLM sent successfully:', response);
                this.sseService.resumeStream();
                this.statusWaitForUser = false;
                this.autoScrollEnabled = true;
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Error sending answer to LLM:', error);
            },
        });
    }

    private mergeMessages(incoming: GraphMessage[]): void {
        const toAdd = incoming.filter((m) => {
            const key = this.getMessageKey(m);
            if (this.seenKeys.has(key)) return false;
            this.seenKeys.add(key);
            return true;
        });
        if (toAdd.length === 0) return;
        this.messages = [...this.messages, ...toAdd].sort((a, b) => a.execution_order - b.execution_order);
    }

    private insertSubgraphMessages(subgraphExecutionId: string, incoming: GraphMessage[]): void {
        const toAdd = incoming.filter((m) => {
            const key = this.getMessageKey(m);
            if (this.seenKeys.has(key)) return false;
            this.seenKeys.add(key);
            return true;
        });
        if (toAdd.length === 0) return;

        const finishIdx = this.messages.findIndex(
            (m) =>
                m.message_data.message_type === MessageType.SUBGRAPH_FINISH &&
                (m.message_data as unknown as Record<string, unknown>)['subgraph_execution_id'] === subgraphExecutionId
        );

        toAdd.sort((a, b) => a.execution_order - b.execution_order);

        if (finishIdx !== -1) {
            // Insert just before subgraph_finish — each new page accumulates at the bottom
            this.messages = [...this.messages.slice(0, finishIdx), ...toAdd, ...this.messages.slice(finishIdx)];
        } else {
            // subgraph_finish not yet loaded — fall back to inserting after subgraph_start
            const startIdx = this.messages.findIndex(
                (m) =>
                    m.message_data.message_type === MessageType.SUBGRAPH_START &&
                    (m.message_data as unknown as Record<string, unknown>)['subgraph_execution_id'] ===
                        subgraphExecutionId
            );
            if (startIdx === -1) return;
            this.messages = [...this.messages.slice(0, startIdx + 1), ...toAdd, ...this.messages.slice(startIdx + 1)];
        }
    }

    private loadSubgraphMessages(subgraphExecutionId: string, offset: number): void {
        if (this.loadingSubgraphIds.has(subgraphExecutionId) || !this.sessionId) return;
        this.loadingSubgraphIds.add(subgraphExecutionId);

        this.graphSessionService
            .getSessionMessages(+this.sessionId, this.PAGE_SIZE, offset, subgraphExecutionId)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.insertSubgraphMessages(subgraphExecutionId, response.results);
                    this.subgraphOffsets.set(subgraphExecutionId, offset + this.PAGE_SIZE);
                    this.subgraphHasMore.set(subgraphExecutionId, response.next !== null);
                    this.loadingSubgraphIds.delete(subgraphExecutionId);
                    this.rebuildMessageState(this.messages);
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.loadingSubgraphIds.delete(subgraphExecutionId);
                },
            });
    }

    private loadMoreSubgraphPage(subgraphExecutionId: string): void {
        const offset = this.subgraphOffsets.get(subgraphExecutionId) ?? 0;
        this.loadSubgraphMessages(subgraphExecutionId, offset);
    }

    public loadMoreMessages(): void {
        if (this.isLoadingMore || !this.hasMore || !this.sessionId) return;
        this.isLoadingMore = true;
        this.cdr.markForCheck();

        this.graphSessionService
            .getSessionMessages(+this.sessionId, this.PAGE_SIZE, this.currentOffset)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.currentOffset += this.PAGE_SIZE;
                    this.mergeMessages(response.results);
                    this.rebuildMessageState(this.messages);
                    this.hasMore = response.next !== null;
                    this.isLoadingMore = false;
                    this.cdr.markForCheck();
                    if (this.hasMore && this.isInsideOpenSubgraph()) {
                        this.loadMoreMessages();
                    }
                },
                error: () => {
                    this.isLoadingMore = false;
                    this.cdr.markForCheck();
                },
            });
    }

    // Bugfix (safe reconcile): once the run reaches a terminal status the backend has
    // persisted every message, so re-fetch the full list and merge it. mergeMessages() dedups
    // via seenKeys, so this only ADDS messages the realtime SSE stream missed (no duplicates).
    // Deliberately separate from loadMoreMessages() so it never touches the scroll-pagination
    // state and isn't affected by it.
    private reconcileMessagesFromServer(offset = 0): void {
        if (!this.sessionId) return;
        this.graphSessionService
            .getSessionMessages(+this.sessionId, this.PAGE_SIZE, offset)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    this.mergeMessages(response.results);
                    this.rebuildMessageState(this.messages);
                    this.processMessages();
                    this.messagesChanged.emit(this.messages);
                    this.cdr.markForCheck();
                    if (response.next !== null) {
                        this.reconcileMessagesFromServer(offset + this.PAGE_SIZE);
                    }
                },
            });
    }

    private isInsideOpenSubgraph(): boolean {
        if (!this.messageContexts.length) return false;
        const last = this.messageContexts[this.messageContexts.length - 1];
        let postDepth = last.depth;
        if (last.isSubgraphStart) postDepth++;
        else if (last.isSubgraphFinish && postDepth > 0) postDepth--;
        return postDepth > 0;
    }

    private rebuildMessageState(messages: GraphMessage[]): void {
        this.buildMessageContexts(messages);
        this.syncDrillPaths(messages);
        this.updateDrilldownView();
    }

    private buildMessageContexts(messages: GraphMessage[]): void {
        this.messageContexts = [];
        this.messageContextByKey.clear();
        this.messageByKey.clear();

        const stack: string[] = [];
        messages.forEach((message, index) => {
            const key = this.getMessageKey(message);
            const isSubgraphStart = isMessageType(message, MessageType.SUBGRAPH_START);
            const isSubgraphFinish = isMessageType(message, MessageType.SUBGRAPH_FINISH);
            const path = [...stack];
            const context: MessageContext = {
                key,
                index,
                depth: stack.length,
                path,
                isSubgraphStart,
                isSubgraphFinish,
            };

            this.messageContexts.push(context);
            this.messageContextByKey.set(key, context);
            this.messageByKey.set(key, message);

            if (isSubgraphStart) {
                stack.push(key);
            } else if (isSubgraphFinish && stack.length > 0) {
                stack.pop();
            }
        });

        this.buildMessageGraphContexts(messages);
    }

    private syncDrillPaths(messages: GraphMessage[]): void {
        if (this.drillPaths.size === 0) return;
        const keySet = new Set(messages.map((message) => this.getMessageKey(message)));
        [...this.drillPaths.entries()].forEach(([rootKey, path]) => {
            const isValid = path.every((key) => keySet.has(key));
            if (!isValid) {
                this.drillPaths.delete(rootKey);
                this.closingRootKeys.delete(rootKey);
                this.breadcrumbSearchByRoot.delete(rootKey);
                this.breadcrumbSearchExpandedByRoot.delete(rootKey);
                this.breadcrumbOverflowByRoot.delete(rootKey);
                this.filteredBreadcrumbsByRoot.delete(rootKey);
                this.drilldownEntriesByRoot.delete(rootKey);
                this.currentDrillEntryByRoot.delete(rootKey);
            }
        });
    }

    @HostListener('document:click', ['$event'])
    public onDocumentClick(event: MouseEvent): void {
        const target = event.target as HTMLElement | null;
        if (!target) return;
        if (target.closest('.breadcrumbs-search')) return;
        this.collapseEmptyBreadcrumbSearches();
    }

    @HostListener('window:resize')
    public onWindowResize(): void {
        this.scheduleBreadcrumbOverflowRefresh();
    }

    private collapseEmptyBreadcrumbSearches(): void {
        let didChange = false;
        this.breadcrumbSearchExpandedByRoot.forEach((isExpanded, rootKey) => {
            if (!isExpanded) return;
            const term = this.getBreadcrumbSearchTerm(rootKey).trim();
            if (!term) {
                this.breadcrumbSearchExpandedByRoot.delete(rootKey);
                this.breadcrumbSearchByRoot.delete(rootKey);
                didChange = true;
            }
        });
        if (didChange) {
            this.cdr.markForCheck();
            this.scheduleBreadcrumbOverflowRefresh();
        }
    }

    private updateDrilldownView(): void {
        this.updateVisibleMessages();
        this.updateDrilldownMessages();
        this.updateBreadcrumbs();
        this.updateRootViews();
    }

    private buildMessageEntry(message: GraphMessage, context?: MessageContext | null): MessageViewEntry {
        const resolvedContext = context ?? this.getMessageContext(message);
        const hasNestedMessages = resolvedContext ? this.hasNestedMessagesForContext(resolvedContext) : false;
        const isNestedMessagesOpen = resolvedContext ? this.isNestedMessagesOpenForContext(resolvedContext) : false;
        const index = resolvedContext ? resolvedContext.index : 0;
        const rootKey = resolvedContext ? this.getRootKeyForContext(resolvedContext) : null;
        return {
            key: this.getMessageKey(message),
            message,
            index,
            agent: this.getAgentFromMessage(message),
            project: this.getProjectFromMessage(message),
            subgraphName: this.getSubgraphName(message),
            hasNestedMessages,
            isNestedMessagesOpen,
            shouldShowTransition: this.shouldShowTransition(message, index),
            rootKey,
            rootView: null,
        };
    }

    private updateVisibleMessages(): void {
        // Build a set of message indices to show for code_agent_stream:
        // One card per node name — prefer final, fall back to latest non-final.
        const caShowIndex = new Map<string, number>(); // node_name -> message index to show

        for (const context of this.messageContexts) {
            if (context.path.length !== 0) continue;
            const msg = this.messages[context.index];
            if (msg?.message_data?.message_type !== 'code_agent_stream') continue;

            const isFinal = (msg.message_data as CodeAgentStreamMessageData).is_final === true;
            const existing = caShowIndex.get(msg.name);

            if (isFinal) {
                caShowIndex.set(msg.name, context.index);
            } else if (existing === undefined) {
                caShowIndex.set(msg.name, context.index);
            } else {
                const existingMsg = this.messages[existing];
                if ((existingMsg?.message_data as CodeAgentStreamMessageData)?.is_final !== true) {
                    caShowIndex.set(msg.name, context.index);
                }
            }
        }

        const caShowSet = new Set(caShowIndex.values());

        this.visibleMessageEntries = this.messageContexts
            .filter((context) => context.path.length === 0)
            .filter((context) => {
                const msg = this.messages[context.index];
                const type = msg?.message_data?.message_type;
                if (!type || !RENDERABLE_MESSAGE_TYPES.has(type)) return false;
                if (type !== MessageType.CODE_AGENT_STREAM) return true;
                return caShowSet.has(context.index);
            })
            .map((context) => this.buildMessageEntry(this.messages[context.index], context));
    }

    private updateDrilldownMessages(): void {
        this.drilldownEntriesByRoot.clear();
        this.currentDrillEntryByRoot.clear();

        this.drillPaths.forEach((path, rootKey) => {
            const nestedEntries = this.messageContexts
                .filter((context) => this.pathsEqual(context.path, path))
                .map((context) => this.buildMessageEntry(this.messages[context.index], context));
            this.drilldownEntriesByRoot.set(rootKey, nestedEntries);

            const currentKey = path.length === 0 ? rootKey : path[path.length - 1];
            const currentMessage = this.messageByKey.get(currentKey) ?? null;
            const currentContext = currentMessage ? (this.messageContextByKey.get(currentKey) ?? null) : null;
            this.currentDrillEntryByRoot.set(
                rootKey,
                currentMessage ? this.buildMessageEntry(currentMessage, currentContext) : null
            );
        });
    }

    private updateBreadcrumbs(): void {
        this.breadcrumbsByRoot.clear();
        this.filteredBreadcrumbsByRoot.clear();
        this.drillPaths.forEach((path, rootKey) => {
            this.breadcrumbsByRoot.set(
                rootKey,
                path.map((key) => ({
                    key,
                    label: this.getBreadcrumbLabel(key),
                }))
            );
            this.updateFilteredBreadcrumbs(rootKey);
        });
        this.scheduleBreadcrumbOverflowRefresh();
    }

    private updateRootViews(): void {
        if (this.visibleMessageEntries.length === 0) return;
        const rootViewsByKey = new Map<string, RootDrilldownView>();
        this.drillPaths.forEach((_path, rootKey) => {
            rootViewsByKey.set(rootKey, {
                rootKey,
                breadcrumbs: this.breadcrumbsByRoot.get(rootKey) ?? [],
                filteredBreadcrumbs: this.filteredBreadcrumbsByRoot.get(rootKey) ?? [],
                drilldownEntries: this.drilldownEntriesByRoot.get(rootKey) ?? [],
                currentDrillEntry: this.currentDrillEntryByRoot.get(rootKey) ?? null,
                breadcrumbSearchTerm: this.breadcrumbSearchByRoot.get(rootKey) ?? '',
                breadcrumbSearchExpanded: this.breadcrumbSearchExpandedByRoot.get(rootKey) ?? false,
                hasBreadcrumbOverflow: this.breadcrumbOverflowByRoot.get(rootKey) ?? false,
                isClosing: this.closingRootKeys.has(rootKey),
            });
        });

        this.visibleMessageEntries = this.visibleMessageEntries.map((entry) => {
            if (!entry.rootKey) {
                return entry.rootView ? { ...entry, rootView: null } : entry;
            }
            const isRootEntry = entry.rootKey === this.getMessageKey(entry.message);
            const rootView = isRootEntry ? (rootViewsByKey.get(entry.rootKey) ?? null) : null;
            if (entry.rootView === rootView) return entry;
            return { ...entry, rootView };
        });
    }

    private updateFilteredBreadcrumbs(rootKey: string): void {
        const breadcrumbs = this.breadcrumbsByRoot.get(rootKey) ?? [];
        const term = (this.breadcrumbSearchByRoot.get(rootKey) ?? '').trim().toLowerCase();
        const withIndex = breadcrumbs.map((crumb, index) => ({ ...crumb, index }));
        if (!term) {
            this.filteredBreadcrumbsByRoot.set(rootKey, withIndex);
            return;
        }
        this.filteredBreadcrumbsByRoot.set(
            rootKey,
            withIndex.filter((crumb) => crumb.label?.toLowerCase().includes(term))
        );
    }

    private updateBreadcrumbOverflow(rootKey: string, container: HTMLElement): void {
        const hasOverflow = container.scrollWidth > container.clientWidth + 1;
        if (this.breadcrumbOverflowByRoot.get(rootKey) === hasOverflow) return;
        this.breadcrumbOverflowByRoot.set(rootKey, hasOverflow);
        this.updateRootViews();
        this.cdr.markForCheck();
    }

    private scheduleBreadcrumbOverflowRefresh(): void {
        if (this.breadcrumbOverflowRefreshId !== null) return;
        this.breadcrumbOverflowRefreshId = window.setTimeout(() => {
            this.breadcrumbOverflowRefreshId = null;
            this.refreshBreadcrumbOverflow();
        }, 0);
    }

    private refreshBreadcrumbOverflow(): void {
        if (!this.breadcrumbScrollers) return;
        this.breadcrumbScrollers.forEach((scroller) => {
            const element = scroller.nativeElement;
            const rootKey = element.dataset['rootKey'];
            if (!rootKey) return;
            this.updateBreadcrumbOverflow(rootKey, element);
        });
    }

    private getMessageContext(message: GraphMessage): MessageContext | null {
        const key = this.getMessageKey(message);
        return this.messageContextByKey.get(key) || null;
    }

    private getMessageKey(message: GraphMessage): string {
        // Stable key for code_agent_stream: one component per node name
        if (message.message_data?.message_type === 'code_agent_stream') {
            return `ca_stream_${message.name}`;
        }
        return message.uuid ?? `${message.id}-${message.execution_order}-${message.created_at}`;
    }

    private getRootKeyForContext(context: MessageContext): string | null {
        if (context.path.length > 0) {
            return context.path[0];
        }

        return context.isSubgraphStart ? context.key : null;
    }

    private pathsEqual(left: string[], right: string[]): boolean {
        if (left.length !== right.length) return false;
        return left.every((value, index) => value === right[index]);
    }
}
