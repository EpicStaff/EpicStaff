import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  OnInit,
  OnDestroy,
  HostListener,
  AfterViewInit,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { FlowService } from '../../../../visual-programming/services/flow.service';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import {
  CreateGraphDtoRequest,
  GraphDto,
  UpdateGraphDtoRequest,
} from '../../../../features/flows/models/graph.model';
import { FlowHeaderComponent } from './components/header/flow-header.component';
import { FlowGraphComponent } from '../../../../visual-programming/flow-graph/flow-graph.component';
import {
  catchError,
  EMPTY,
  finalize,
  forkJoin,
  map,
  Observable,
  of,
  Subject,
  switchMap,
  takeUntil,
  tap,
  throwError,
} from 'rxjs';

import { ConditionalEdgeService } from './services/conditional-edge.service';
import { CrewNodeService } from './services/crew-node.service';
import { EdgeService } from './services/edge.service';
import { PythonNodeService } from './services/python-node.service';
import { RunGraphService } from '../../../../services/run-graph-session.service';
import { StartNodeService } from './services/start-node.service';
import { StartNode, CreateStartNodeRequest } from './models/start-node.model';

import {
  ConditionalEdge,
  CreateConditionalEdgeRequest,
  CustomConditionalEdgeModelForNode,
  GetConditionalEdgeRequest,
} from './models/conditional-edge.model';
import { CreateEdgeRequest, Edge } from './models/edge.model';
import { GetProjectRequest } from '../../../../features/projects/models/project.model';

import { CreateCrewNodeRequest, CrewNode } from './models/crew-node.model';
import {
  CreatePythonNodeRequest,
  PythonNode,
} from './models/python-node.model';

import { v4 as uuidv4 } from 'uuid';
import { ToastService } from '../../../../services/notifications/toast.service';
import { ConnectionModel } from '../../../../visual-programming/core/models/connection.model';
import { FlowModel } from '../../../../visual-programming/core/models/flow.model';
import { GroupNodeModel } from '../../../../visual-programming/core/models/group.model';
import {
  NodeModel,
  StartNodeModel,
} from '../../../../visual-programming/core/models/node.model';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { GraphUpdateService } from '../../../../visual-programming/services/graph/save-graph.service';
import { Dialog as CdkDialog } from '@angular/cdk/dialog';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { FlowSessionsListComponent } from '../../../../features/flows/components/flow-sessions-dialog/flow-sessions-list.component';
import {
  ConfirmationDialogComponent,
  ConfirmationDialogData,
} from '../../../../shared/components/cofirm-dialog/confirmation-dialog.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog/confimation-dialog.service';

import { isEqual } from 'lodash';
import { CanComponentDeactivate } from '../../../../core/guards/unsaved-changes.guard';
@Component({
  selector: 'app-flow-visual-programming',
  standalone: true,
  imports: [FlowHeaderComponent, FlowGraphComponent, SpinnerComponent],
  templateUrl: './flow-visual-programming.component.html',
  styleUrl: './flow-visual-programming.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowVisualProgrammingComponent
  implements OnInit, OnDestroy, CanComponentDeactivate
{
  public isLoaded = false;
  public graph!: GraphDto;

  public isSaving = false;
  public isRunning = false;

  private initialState: FlowModel | undefined;
  private readonly destroy$ = new Subject<void>();
  private isNavigatingToRun = false;

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly flowStorageService: FlowsStorageService,
    private readonly flowService: FlowService,
    private readonly flowApiService: FlowsApiService,
    private readonly cdr: ChangeDetectorRef,
    private readonly toastService: ToastService,
    private readonly graphUpdateService: GraphUpdateService,
    private readonly runGraphService: RunGraphService,
    private readonly startNodeService: StartNodeService,
    private readonly dialog: CdkDialog,
    private readonly confirmationDialogService: ConfirmationDialogService
  ) {}

  public ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) {
      console.warn('Invalid graph ID.');
      return;
    }

    this.fetchGraph(id);
  }

  private fetchGraph(graphId: number): void {
    this.flowApiService
      .getGraphById(graphId)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => this.cdr.markForCheck())
      )
      .subscribe({
        next: (graph: GraphDto) => {
          console.log('view flow page fetched graph:', graph);

          this.graph = graph;

          this.isLoaded = true;
          this.initialState = graph.metadata;
        },
        error: (err) => {
          console.error('Error fetching graph:', err);
          this.toastService.error('Failed to load graph');
        },
      });
  }

  public handleSaveFlow(showNotif: boolean): void {
    if (this.isSaving) return;

    this.isSaving = true;
    const flowState: FlowModel = this.flowService.getFlowState();
    console.log('floew state that i got from service on saveflow', flowState);

    const startNodeInFlow = flowState.nodes.find(
      (node) => node.type === NodeType.START
    ) as StartNodeModel | undefined;

    if (!startNodeInFlow) {
      console.log('no start node in flow');

      this.saveGraphDirectly(flowState, showNotif);
      return;
    }
    console.log('save graph with start node');

    this.saveGraphWithStartNode(flowState, startNodeInFlow, showNotif);
  }

  private saveGraphWithStartNode(
    flowState: FlowModel,
    startNode: StartNodeModel,
    showNotif: boolean
  ): void {
    const initialStateData = startNode.data.initialState;

    this.startNodeService
      .getStartNodes()
      .pipe(
        takeUntil(this.destroy$),
        switchMap((startNodes) => {
          const matchingStartNode = startNodes.find(
            (sn) => sn.graph === this.graph.id
          );

          if (matchingStartNode) {
            return this.startNodeService.updateStartNode(matchingStartNode.id, {
              graph: this.graph.id,
              variables: initialStateData,
            });
          }

          return this.startNodeService.createStartNode({
            graph: this.graph.id,
            variables: initialStateData,
          });
        }),
        switchMap(() =>
          this.graphUpdateService.saveGraph(flowState, this.graph)
        ),
        finalize(() => {
          this.isSaving = false;
          this.cdr.markForCheck();
        })
      )
      .subscribe({
        next: (result) => {
          this.graph = result.graph;
          this.initialState = flowState;
          if (showNotif) {
            this.toastService.success('Graph saved successfully');
          }
        },
        error: (err) => {
          this.toastService.error(
            `Failed to save graph: ${err?.error?.error || 'Unknown error'}`
          );
          console.error('Error saving graph:', err);
        },
      });
  }

  private saveGraphDirectly(flowState: FlowModel, showNotif: boolean): void {
    this.graphUpdateService
      .saveGraph(flowState, this.graph)
      .pipe(
        takeUntil(this.destroy$),
        finalize(() => {
          this.isSaving = false;
          this.cdr.markForCheck();
        })
      )
      .subscribe({
        next: (result) => {
          this.graph = result.graph;
          this.initialState = flowState;
          if (showNotif) {
            this.toastService.success('Graph saved successfully');
          }
        },
        error: (err) => {
          this.toastService.error(
            `Failed to save graph: ${err?.error?.error || 'Unknown error'}`
          );
          console.error('Error saving graph:', err);
        },
      });
  }

  private saveGraphForRun(): Observable<any> {
    const flowState: FlowModel = this.flowService.getFlowState();

    const startNodeInFlow = flowState.nodes.find(
      (node) => node.type === NodeType.START
    ) as StartNodeModel | undefined;

    if (!startNodeInFlow) {
      return this.graphUpdateService.saveGraph(flowState, this.graph).pipe(
        tap((result) => {
          this.graph = result.graph;
          this.initialState = flowState;
        })
      );
    }

    const initialStateData = startNodeInFlow.data.initialState;

    return this.startNodeService.getStartNodes().pipe(
      switchMap((startNodes) => {
        const matchingStartNode = startNodes.find(
          (sn) => sn.graph === this.graph.id
        );

        if (matchingStartNode) {
          return this.startNodeService.updateStartNode(matchingStartNode.id, {
            graph: this.graph.id,
            variables: initialStateData,
          });
        }

        return this.startNodeService.createStartNode({
          graph: this.graph.id,
          variables: initialStateData,
        });
      }),
      switchMap(() => this.graphUpdateService.saveGraph(flowState, this.graph)),
      tap((result) => {
        this.graph = result.graph;
        this.initialState = flowState;
      })
    );
  }

  public handleRunFlow(): void {
    if (this.isRunning || !this.graph?.id) return;

    this.isRunning = true;

    // Check if we have unsaved changes and save first if needed
    const saveFirst$ = this.hasUnsavedChanges()
      ? this.saveGraphForRun()
      : of(null);

    saveFirst$
      .pipe(
        switchMap(() => this.runGraphService.runGraph(this.graph.id)),
        takeUntil(this.destroy$),
        finalize(() => {
          this.isRunning = false;
          this.cdr.markForCheck();
        })
      )
      .subscribe({
        next: (response: any) => {
          this.isNavigatingToRun = true;
          this.router.navigate([
            'graph',
            this.graph.id,
            'session',
            response.session_id,
          ]);
        },
        error: (error: any) => {
          this.toastService.error(
            `Failed to run graph: ${error?.error?.error || 'Unknown error'}`
          );
          console.error('Failed to run graph:', error);
        },
      });
  }

  public handleViewSessions(): void {
    if (!this.graph) return;
    this.dialog.open(FlowSessionsListComponent, {
      data: { flow: this.graph },
      panelClass: 'custom-dialog-panel',
    });
  }

  @HostListener('window:beforeunload', ['$event'])
  public handleBeforeUnload(event: BeforeUnloadEvent): string | void {
    if (this.hasUnsavedChanges()) {
      event.preventDefault();
      return (event.returnValue = '');
    }
  }

  private hasUnsavedChanges(): boolean {
    const currentState = this.flowService.getFlowState();

    return !isEqual(currentState, this.initialState);
  }

  public canDeactivate(): boolean | Observable<boolean> {
    // Allow navigation if it's triggered by the run button
    if (this.isNavigatingToRun) {
      return true;
    }

    if (this.hasUnsavedChanges()) {
      return this.confirmationDialogService
        .confirm({
          title: 'Unsaved Changes',
          message:
            'You have unsaved changes in flow. Do you really want to leave?',
          confirmText: 'Save and leave',
          cancelText: 'Stay on flow',
          type: 'warning',
        })
        .pipe(
          switchMap((result) => {
            if (result === 'close') {
              return of(false);
            }
            if (result === true) {
              console.log('save flow');

              this.handleSaveFlow(true);
              return of(true);
            }
            return of(result as boolean);
          })
        );
    }
    return true;
  }
  public ngOnDestroy(): void {
    // this.destroy$.next();
    // this.destroy$.complete();
  }
}
