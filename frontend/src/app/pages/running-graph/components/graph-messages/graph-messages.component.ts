import {
  Component,
  Input,
  OnInit,
  OnDestroy,
  OnChanges,
  SimpleChanges,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Output,
  EventEmitter,
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
  GraphSession,
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
import { isMessageType } from './helper_functions/message-helper';
import { RunGraphPageService } from '../../run-graph-page.service';
import { RunSessionSSEService } from '../../../run-graph-page/run-graph-page-body/graph-session-sse.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';

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
  ],
  templateUrl: './graph-messages.component.html',
  styleUrls: ['./graph-messages.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [RunSessionSSEService],
})
export class GraphMessagesComponent implements OnInit, OnDestroy, OnChanges {
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
  // Lookup maps for quick reference
  private agentMap: Map<number, GetAgentRequest> = new Map();
  private taskMap: Map<number, GetTaskRequest> = new Map();

  private destroy$ = new Subject<void>();

  constructor(
    public sseService: RunSessionSSEService,
    private agentsService: AgentsService,
    private tasksService: TasksService,
    private cdr: ChangeDetectorRef,
    private answerToLLMService: AnswerToLLMService,
    private runGraphPageService: RunGraphPageService, // Use RunGraphPageService
    private flowService: FlowsApiService
  ) {
    effect(() => {
      const messages = this.sseService.messages();
      this.messagesChanged.emit(messages);
      this.processMessages();
      this.checkIfFinish();
      this.cdr.markForCheck();
    });

    effect(() => {
      const status = this.sseService.status();
      this.sessionStatusChanged.emit(status);
      this.statusWaitForUser = status === GraphSessionStatus.WAITING_FOR_USER;
      this.showUserInputWithDelay = this.statusWaitForUser;
      this.checkIfFinish();
      this.cdr.markForCheck();
    });

    effect(() => {
      const memories = this.sseService.memories();
      this.runGraphPageService.setMemories(memories);
    });
  }

  get isProcessing(): boolean {
    return this.isLoading || this.sseService.isStreaming();
  }

  public ngOnInit(): void {
    this.loadData();
  }

  public ngOnDestroy(): void {
    this.sseService.stopStream();
    this.destroy$.next();
    this.destroy$.complete();
  }

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes['sessionId'] && !changes['sessionId'].firstChange) {
      // Clean up previous subscriptions and state
      this.destroy$.next();
      this.sseService.stopStream();
      this.isLoading = true;
      this.session = null;
      this.animatedIndices = {};
      this.updateSessionStatusData = null;
      this.statusWaitForUser = false;
      this.showUserInputWithDelay = false;
      this.cdr.markForCheck();
      // Load new session data
      if (this.sessionId) {
        this.loadData();
      }
    }
  }

  private loadData(): void {
    if (!this.sessionId || !this.graphId) return;

    this.sseService.startStream(this.sessionId!);

    this.flowService
      .getGraphById(this.graphId)
      .pipe(
        takeUntil(this.destroy$),
        exhaustMap((graph) => {
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
          });
        })
      )
      .subscribe({
        next: ({ agents, tasks }) => {
          this.agents = agents;
          this.tasks = tasks;
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

  private checkIfFinish() {
    const messages = this.sseService.messages();
    if (messages.length > 0) {
      const lastMessage: GraphMessage = messages[messages.length - 1];
      const lastTime = lastMessage.created_at;
      const sameTimeMessages = messages.filter(
        (msg) => msg.created_at === lastTime
      );
      const sessionStatus = this.sseService.status();

      if (
        sameTimeMessages.some(
          (msg) => msg.message_data.message_type === 'finish'
        ) &&
        sessionStatus === GraphSessionStatus.ENDED
      ) {
        this.sseService.stopStream();
      } else if (
        sameTimeMessages.some(
          (msg) => msg.message_data.message_type === 'error'
        ) &&
        sessionStatus === GraphSessionStatus.ERROR
      ) {
        this.sseService.stopStream();
      } else if (
        sameTimeMessages.some(
          (msg) =>
            msg.message_data.message_type === 'update_session_status' &&
            msg.message_data.status === GraphSessionStatus.WAITING_FOR_USER
        ) &&
        sessionStatus === GraphSessionStatus.WAITING_FOR_USER
      ) {
        this.sseService.stopStream();
      } else if (sessionStatus === GraphSessionStatus.EXPIRED) {
        this.sseService.stopStream();
      }
    }
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
    // Return null if message is invalid
    if (!message) return null;

    // Try to find project through message name
    if (message.name) {
      console.log('Using message name for finish message:', message.name);
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

    const prevMessage = this.sseService.messages()[index - 1];

    // If current message is 'start' and previous is 'finish', show transition
    return (
      isMessageType(currentMessage, MessageType.START) &&
      isMessageType(prevMessage, MessageType.FINISH)
    );
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
}
