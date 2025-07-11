import {
  Component,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { RouterModule } from '@angular/router';
import { GraphMessagesComponent } from './components/graph-messages/graph-messages.component';
import { RunningGraphHeaderComponent } from './components/header/run-graph-header.component';
import { FlowRepresentationComponent } from './components/graph-reprsentation/graph-representation.component';
import { GraphSessionStatus } from '../../features/flows/services/flows-sessions.service';

import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { GraphMessage } from './models/graph-session-message.model';
import { GraphDto } from '../../features/flows/models/graph.model';
import { FlowsApiService } from '../../features/flows/services/flows-api.service';

@Component({
  selector: 'app-running-graph',
  standalone: true,
  imports: [
    CommonModule,

    RouterModule,
    RunningGraphHeaderComponent,
    GraphMessagesComponent,
  ],
  template: `
    <div class="running-graph-container">
      <app-running-graph-header
        [graphId]="graphId"
        [sessionId]="sessionId"
        [graphName]="graphData?.name"
        [sessionStatus]="currentSessionStatus"
        [graphData]="graphData"
      >
      </app-running-graph-header>

      <div class="content-container">
        <app-graph-messages
          [graphId]="graphId"
          [sessionId]="sessionId"
          (sessionStatusChanged)="handleSessionStatusChange($event)"
          (messagesChanged)="handleMessagesChanged($event)"
        >
        </app-graph-messages>
        <!-- <app-flow-representation [graphData]="graphData" [messages]="messages">
        </app-flow-representation> -->
      </div>
    </div>
  `,
  styles: [
    `
      .running-graph-container {
        height: 100%;
        display: flex;
        flex-direction: column;
        overflow: hidden;

        .content-container {
          flex: 1;
          display: flex;
          overflow: hidden;
          gap: 1rem;
          padding: 1rem 3rem;
          padding-top: 0;
        }
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunningGraphComponent implements OnInit, OnDestroy {
  public graphId: number | null = null;
  public sessionId: string | null = null;
  public graphData: GraphDto | null = null;
  public currentSessionStatus: GraphSessionStatus | null = null;
  public messages: GraphMessage[] = [];

  private destroy$ = new Subject<void>();

  constructor(
    private route: ActivatedRoute,
    private graphService: FlowsApiService,
    private cdr: ChangeDetectorRef
  ) {}

  public ngOnInit(): void {
    // Extract graphId and sessionId from route parameters
    this.route.paramMap.pipe(takeUntil(this.destroy$)).subscribe((params) => {
      const newGraphId = Number(params.get('graphId'));
      const newSessionId = params.get('sessionId');

      // Only reload graph data if graphId changed
      if (newGraphId !== this.graphId) {
        this.graphId = newGraphId;
        if (this.graphId) {
          this.loadGraphData(this.graphId);
        }
      } else {
        // Just update the graphId if it's the same
        this.graphId = newGraphId;
      }

      // Update sessionId and trigger change detection
      if (newSessionId !== this.sessionId) {
        console.log('Session changed from', this.sessionId, 'to', newSessionId);
        this.sessionId = newSessionId;
        this.currentSessionStatus = null; // Reset status for new session
        this.messages = []; // Clear messages for new session
        this.cdr.markForCheck();
      }
    });
  }

  public ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private loadGraphData(graphId: number): void {
    this.graphService
      .getGraphById(graphId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (graph) => {
          this.graphData = graph;
          this.cdr.markForCheck();
        },
        error: (err) => {
          console.error('Failed to load graph data:', err);
          this.cdr.markForCheck();
        },
      });
  }

  public handleSessionStatusChange(status: GraphSessionStatus): void {
    this.currentSessionStatus = status;
    this.cdr.markForCheck();
  }

  public handleMessagesChanged(newMessages: GraphMessage[]): void {
    this.messages = newMessages;
    this.cdr.markForCheck();
  }
}
