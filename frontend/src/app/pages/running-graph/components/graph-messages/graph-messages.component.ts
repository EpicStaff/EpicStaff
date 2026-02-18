import {
  Component,
  Input,
  OnInit,
  OnDestroy,
  OnChanges,
  AfterViewInit,
  SimpleChanges,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Output,
  EventEmitter,
  HostListener,
  ViewChildren,
  ElementRef,
  QueryList,
  effect,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MarkdownModule } from 'ngx-markdown';
import { AgentsService } from '../../../../services/staff.service';
import { TasksService } from '../../../../services/tasks.service';
import { LoadingDotsComponent } from './components/loading-animation/loading-animation.component';

import { GetAgentRequest } from '../../../../shared/models/agent.model';
import { GetTaskRequest } from '../../../../shared/models/task.model';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';
import { forkJoin, Observable, of, Subject } from 'rxjs';
import { takeUntil, map, exhaustMap } from 'rxjs/operators';

import {
  GraphSessionStatus,
  GraphSession, GraphSessionService, SessionUpdates,
} from '../../../../features/flows/services/flows-sessions.service';
import {
  GraphMessage,
  MessageType,
} from '../../models/graph-session-message.model';
import { StartMessageComponent } from './components/start-message/start-message.component';
import { AgentMessageComponent } from './components/agent-message/agent-message.component';
import { TaskMessageComponent } from './components/task-message/task-message.component';
import { PythonMessageComponent } from './components/python-message/python-message.component';
import { LlmMessageComponent } from './components/llm-message/llm-message.component';
import { FinishMessageComponent } from './components/finish-message/finish-message.component';
import { AgentFinishMessageComponent } from './components/agent-finish/agent-finish.component';
import { ErrorMessageComponent } from './components/error-message/error-message.component';
import { ProjectTransitionComponent } from './components/transition/project-transition.component';
import { WaitForUserInputComponent } from './components/user-input-component/user-input-component.component';
import { SessionStatusMessageData } from '../../models/update-session-status.model';
import { AnswerToLLMService } from '../../../../services/answerToLLMService.service';
import { UserMessageComponent } from './components/user-message/user-message.component';
import { SubgraphStartMessageComponent } from './components/subgraph-start-message/subgraph-start-message.component';
import { SubgraphFinishMessageComponent } from './components/subgraph-finish-message/subgraph-finish-message.component';
import { isMessageType } from './helper_functions/message-helper';
import { RunGraphPageService } from '../../run-graph-page.service';
import { RunSessionSSEService } from '../../../run-graph-page/run-graph-page-body/graph-session-sse.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import { ExtractedChunksMessageComponent } from './components/extracted-chunks/extracted-chunks-message.component';
import { WarningMessagesComponent } from '../warning-messages/warning-messages.component';

interface MessageContext {
  key: string;
  index: number;
  depth: number;
  path: string[];
  isSubgraphStart: boolean;
  isSubgraphFinish: boolean;
}

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
    WarningMessagesComponent,
    SubgraphStartMessageComponent,
    SubgraphFinishMessageComponent,
  ],
  templateUrl: './graph-messages.component.html',
  styleUrls: ['./graph-messages.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [RunSessionSSEService],
})
export class GraphMessagesComponent
  implements OnInit, OnDestroy, OnChanges, AfterViewInit
{
  @Input() graphId: number | null = null;
  @Input() sessionId: string | null = null;
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
  public connectionStatus:
    | 'connected'
    | 'connecting'
    | 'disconnected'
    | 'reconnecting'
    | 'manually_disconnected' = 'disconnected';
  public reconnectAttempts: number = 0;

  // Lookup maps for quick reference
  private agentMap: Map<number, GetAgentRequest> = new Map();
  private taskMap: Map<number, GetTaskRequest> = new Map();

  public messages: GraphMessage[] = [];
  public visibleMessageEntries: MessageViewEntry[] = [];

  private drillPaths = new Map<string, string[]>();
  private breadcrumbsByRoot = new Map<string, { key: string; label: string }[]>();
  private filteredBreadcrumbsByRoot = new Map<
    string,
    { key: string; label: string; index: number }[]
  >();
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

  @ViewChildren('breadcrumbsScroller')
  private breadcrumbScrollers!: QueryList<ElementRef<HTMLElement>>;

  constructor(
    public sseService: RunSessionSSEService,
    private agentsService: AgentsService,
    private tasksService: TasksService,
    private cdr: ChangeDetectorRef,
    private answerToLLMService: AnswerToLLMService,
    private runGraphPageService: RunGraphPageService,
    private flowService: FlowsApiService,
    private graphSessionService: GraphSessionService,
  ) {
    effect(() => {
      const messages = this.sseService.messages();
      this.messages = messages;
      this.messagesChanged.emit(messages);
      this.rebuildMessageState(messages);
      this.processMessages();
      this.checkIfFinish();
      this.cdr.markForCheck();
    });

    effect(() => {
      const status = this.sseService.status();
      this.sessionStatusChanged.emit(status);
      this.statusWaitForUser = status === GraphSessionStatus.WAITING_FOR_USER;
      this.showUserInputWithDelay = this.statusWaitForUser;

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

  public ngOnDestroy(): void {
    this.sseService.stopStream();
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
      this.isLoading = true;
      this.session = null;
      this.animatedIndices = {};
      this.updateSessionStatusData = null;
      this.statusWaitForUser = false;
      this.showUserInputWithDelay = false;
      this.warningMessages = null;
      this.messages = [];
      this.visibleMessageEntries = [];
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
    if (!this.sessionId || !this.graphId) return;

    this.sseService.startStream(this.sessionId!);

    // Load warning messages
    this.graphSessionService
      .getSessionWarnings(this.sessionId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.warningMessages = response.messages;
          this.cdr.markForCheck();
        },
        error: (err) => {
          console.error('Failed to load warnings:', err);
          this.warningMessages = null;
        },
      });

    this.flowService
      .getGraphById(this.graphId)
      .pipe(
        takeUntil(this.destroy$),
        exhaustMap((graph) => {
          this.graphCache.set(graph.id, graph);
          const agentsIDs = new Set(
            graph.crew_node_list.flatMap((node) => node.crew.agents)
          );
          const tasksIDs = new Set(
            graph.crew_node_list.flatMap((node) => node.crew.tasks)
          );

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
          this.graphNameById = new Map(
            graphsLight.map((graph) => [graph.id, graph.name])
          );
          if (this.graphId && this.graphCache.has(this.graphId)) {
            const rootGraph = this.graphCache.get(this.graphId);
            if (rootGraph) {
              this.graphNameById.set(rootGraph.id, rootGraph.name);
            }
          }
          this.rebuildMessageState(this.sseService.messages());
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

      if (
        lastMessage.message_data &&
        lastMessage.message_data.message_type === 'update_session_status'
      ) {
        // Cast the message_data to SessionStatusMessageData interface
        this.updateSessionStatusData =
          lastMessage.message_data as SessionStatusMessageData;

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
    if (!this.graphId) return;
    const graphStack: number[] = [this.graphId];

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

  private getSubgraphIdForNode(
    graphId: number,
    nodeName: string
  ): number | null {
    const graph = this.graphCache.get(graphId);
    if (!graph?.subgraph_node_list?.length) return null;
    const match = graph.subgraph_node_list.find(
      (node) => node.node_name === nodeName
    );
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
          this.rebuildMessageState(this.sseService.messages());
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
      const sameTimeMessages = messages.filter(
        (msg) => msg.created_at === lastTime
      );
      const sessionStatus = this.sseService.status();

      // Check for graph_end message - marks the session as finished
      if (
        sameTimeMessages.some(
          (msg) => msg.message_data.message_type === MessageType.GRAPH_END
        )
      ) {
        this.sseService.stopStream();
        this.updateSessionStatus();
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

      // if (
      //   sameTimeMessages.some(
      //     (msg) => msg.message_data.message_type === 'finish'
      //   ) &&
      //   sessionStatus === GraphSessionStatus.ENDED
      // ) {
      //   this.sseService.stopStream();
      // } else if (
      //   sameTimeMessages.some(
      //     (msg) => msg.message_data.message_type === 'error'
      //   ) &&
      //   sessionStatus === GraphSessionStatus.ERROR
      // ) {
      //   this.sseService.stopStream();
      // } else if (sessionStatus === GraphSessionStatus.EXPIRED) {
      //   this.sseService.stopStream();
      // } else if (sessionStatus === GraphSessionStatus.STOP) {
      //   this.sseService.stopStream();
      // } else if (sessionStatus === GraphSessionStatus.ERROR) {
      //   this.sseService.stopStream();
      // } else if (sessionStatus === GraphSessionStatus.ENDED) {
      //   this.sseService.stopStream();
      // }
      // Note: PENDING is a transitional state - don't stop stream, wait for final status
    }
  }

  private updateSessionStatus(): void {
    this.graphSessionService.getSessionUpdates(this.sessionId!)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: ({ status }: SessionUpdates) => this.sseService.setStatus(status),
        error: (err) => console.log(err),
      });
  }

  public getAgentFromMessage(message: GraphMessage): GetAgentRequest | null {
    if (!message.message_data) return null;

    if (
      (message.message_data.message_type === 'agent' ||
        message.message_data.message_type === 'agent_finish') &&
      'agent_id' in message.message_data
    ) {
      const agentId = message.message_data.agent_id;
      return this.agentMap.get(agentId) || null;
    }

    return null;
  }

  public getProjectFromMessage(
    message: GraphMessage
  ): GetProjectRequest | null {
    if (!message) return null;

    if (message.name) {
      return { name: message.name } as GetProjectRequest;
    }

    return null;
  }

  // Check if we should show transition between sessions
  public shouldShowTransition(
    currentMessage: GraphMessage,
    index: number
  ): boolean {
    // Don't show transition for the first message
    if (index === 0) return false;

    const prevMessage = this.messages[index - 1];

    // If current message is 'start' and previous is 'finish', show transition
    return (
      isMessageType(currentMessage, MessageType.START) &&
      isMessageType(prevMessage, MessageType.FINISH)
    );
  }

  public isIndideSubFlow(message: GraphMessage): boolean {
    return isMessageType(message, MessageType.SUBGRAPH_START) || isMessageType(message, MessageType.SUBGRAPH_FINISH);
  }

  public onViewNestedMessages(message: GraphMessage): void {
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
      }, this.drilldownCloseDelayMs);
    } else {
      this.closingRootKeys.delete(rootKey);
      this.drillPaths.set(rootKey, nextPath);
    }
    this.updateDrilldownView();
  }

  public onBreadcrumbClick(rootKey: string, index: number): void {
    const currentPath = this.drillPaths.get(rootKey);
    if (!currentPath) return;
    this.drillPaths.set(rootKey, currentPath.slice(0, index + 1));
    this.updateDrilldownView();
  }

  public isDrilldownRoot(message: GraphMessage): boolean {
    const context = this.getMessageContext(message);
    return (
      !!context &&
      context.isSubgraphStart &&
      context.path.length === 0 &&
      this.drillPaths.has(context.key)
    );
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

  public getFilteredBreadcrumbs(
    message: GraphMessage
  ): { key: string; label: string; index: number }[] {
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

  public scrollBreadcrumbs(
    container: HTMLElement,
    direction: 'left' | 'right'
  ): void {
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
    // Log or handle the user message
    console.log('User typed message:', message);

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
        this.cdr.markForCheck();
      },
      error: (error) => {
        console.error('Error sending answer to LLM:', error);
      },
    });
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

  private buildMessageEntry(
    message: GraphMessage,
    context?: MessageContext | null
  ): MessageViewEntry {
    const resolvedContext = context ?? this.getMessageContext(message);
    const hasNestedMessages = resolvedContext
      ? this.hasNestedMessagesForContext(resolvedContext)
      : false;
    const isNestedMessagesOpen = resolvedContext
      ? this.isNestedMessagesOpenForContext(resolvedContext)
      : false;
    const index = resolvedContext ? resolvedContext.index : 0;
    const rootKey = resolvedContext
      ? this.getRootKeyForContext(resolvedContext)
      : null;
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
    this.visibleMessageEntries = this.messageContexts
      .filter((context) => context.path.length === 0)
      .map((context) =>
        this.buildMessageEntry(this.messages[context.index], context)
      );
  }

  private updateDrilldownMessages(): void {
    this.drilldownEntriesByRoot.clear();
    this.currentDrillEntryByRoot.clear();

    this.drillPaths.forEach((path, rootKey) => {
      const nestedEntries = this.messageContexts
        .filter((context) => this.pathsEqual(context.path, path))
        .map((context) =>
          this.buildMessageEntry(this.messages[context.index], context)
        );
      this.drilldownEntriesByRoot.set(rootKey, nestedEntries);

      const currentKey = path.length === 0 ? rootKey : path[path.length - 1];
      const currentMessage = this.messageByKey.get(currentKey) ?? null;
      const currentContext = currentMessage
        ? this.messageContextByKey.get(currentKey) ?? null
        : null;
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
        breadcrumbSearchExpanded:
          this.breadcrumbSearchExpandedByRoot.get(rootKey) ?? false,
        hasBreadcrumbOverflow: this.breadcrumbOverflowByRoot.get(rootKey) ?? false,
        isClosing: this.closingRootKeys.has(rootKey),
      });
    });

    this.visibleMessageEntries = this.visibleMessageEntries.map((entry) => {
      if (!entry.rootKey) {
        return entry.rootView ? { ...entry, rootView: null } : entry;
      }
      const isRootEntry = entry.rootKey === this.getMessageKey(entry.message);
      const rootView = isRootEntry
        ? rootViewsByKey.get(entry.rootKey) ?? null
        : null;
      if (entry.rootView === rootView) return entry;
      return { ...entry, rootView };
    });
  }

  private updateFilteredBreadcrumbs(rootKey: string): void {
    const breadcrumbs = this.breadcrumbsByRoot.get(rootKey) ?? [];
    const term = (this.breadcrumbSearchByRoot.get(rootKey) ?? '')
      .trim()
      .toLowerCase();
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

  private updateBreadcrumbOverflow(
    rootKey: string,
    container: HTMLElement
  ): void {
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
