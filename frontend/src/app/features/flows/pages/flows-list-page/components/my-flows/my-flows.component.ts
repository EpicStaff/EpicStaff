import {
  Component,
  ChangeDetectionStrategy,
  signal,
  inject,
  OnInit,
} from '@angular/core';
import { Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { DialogModule, Dialog } from '@angular/cdk/dialog';

import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { GraphDto } from '../../../../models/graph.model';
import {
  FlowCardComponent,
  FlowCardAction,
} from '../../../../components/flow-card/flow-card.component';
import { LoadingSpinnerComponent } from '../../../../../../shared/components/loading-spinner/loading-spinner.component';
import { FlowSessionsListComponent } from '../../../../components/flow-sessions-dialog/flow-sessions-list.component';
import { FlowsApiService } from '../../../../services/flows-api.service';
import { ConfirmationDialogComponent } from '../../../../../../shared/components/cofirm-dialog/confirmation-dialog.component';
import { FlowRenameDialogComponent } from '../../../../components/flow-rename-dialog/flow-rename-dialog.component';
import { RunGraphService } from '../../../../../../services/run-graph-session.service';
import { ToastService } from '../../../../../../services/notifications/toast.service';

@Component({
  selector: 'app-my-flows',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './my-flows.component.html',
  styleUrls: ['./my-flows.component.scss'],
  imports: [
    CommonModule,
    FlowCardComponent,
    LoadingSpinnerComponent,
    DialogModule,
  ],
})
export class MyFlowsComponent implements OnInit {
  private readonly flowsService = inject(FlowsStorageService);
  private readonly flowsApiService = inject(FlowsApiService);
  private readonly runGraphService = inject(RunGraphService);
  private readonly router = inject(Router);
  private readonly dialog = inject(Dialog);
  private readonly toastService = inject(ToastService);

  public readonly error = signal<string | null>(null);
  public readonly filteredFlows = this.flowsService.filteredFlows;
  public readonly isFlowsLoaded = this.flowsService.isFlowsLoaded;

  public ngOnInit(): void {
    if (!this.flowsService.isFlowsLoaded()) {
      this.flowsService.getFlows().subscribe({
        next: () => {},
        error: (err: HttpErrorResponse) => {
          console.error('Error loading flows', err);
          this.error.set('Failed to load flows. Please try again later.');
        },
      });
    }
  }

  public onOpenFlow(id: number): void {
    this.router.navigate(['/flows', id]);
  }

  public handleFlowCardAction(event: FlowCardAction): void {
    const { action, flow } = event;
    switch (action) {
      case 'open':
        this.onOpenFlow(flow.id);
        break;

      case 'delete':
        this.confirmAndDeleteFlow(flow);
        break;

      case 'viewSessions':
        console.log('View sessions for flow:', flow.name);
        this.dialog.open(FlowSessionsListComponent, {
          data: { flow },
          panelClass: 'custom-dialog-panel',
        });
        break;

      case 'rename':
        this.openRenameDialog(flow);
        break;

      case 'run':
        this.runFlow(flow);
        break;

      default:
        console.log(`Action '${action}' not implemented for flow:`, flow.id);
    }
  }

  private confirmAndDeleteFlow(flow: GraphDto): void {
    const dialogRef = this.dialog.open<'confirm' | 'cancel' | 'close'>(
      ConfirmationDialogComponent,
      {
        data: {
          title: 'Delete Flow',
          message: `Are you sure you want to delete the flow "${flow.name}"? This action cannot be undone.`,
          confirmText: 'Delete',
          cancelText: 'Cancel',
          type: 'danger',
        },
      }
    );

    dialogRef.closed.subscribe((result) => {
      if (result === 'confirm') {
        this.flowsService.deleteFlow(flow.id).subscribe({
          next: () => {
            console.log(`Flow ${flow.id} - ${flow.name} deleted successfully.`);
          },
          error: (err) => {
            console.error(`Error deleting flow ${flow.id} - ${flow.name}`, err);
          },
        });
      }
    });
  }

  private openRenameDialog(flow: GraphDto): void {
    const dialogRef = this.dialog.open<string>(FlowRenameDialogComponent, {
      data: { flowName: flow.name },
    });

    dialogRef.closed.subscribe((newName) => {
      if (newName && newName !== flow.name) {
        this.flowsService
          .patchUpdateFlow(flow.id, { name: newName })
          .subscribe({
            next: (updatedFlow) => {
              console.log(`Flow renamed successfully to: ${updatedFlow.name}`);
            },
            error: (err) => {
              console.error(`Error renaming flow ${flow.id}`, err);
            },
          });
      }
    });
  }

  private runFlow(flow: GraphDto): void {
    // Empty inputs object as per API requirements
    const inputs = {};

    this.runGraphService.runGraph(flow.id, inputs).subscribe({
      next: (response) => {
        console.log('Flow execution started:', response);

        if (response && response.session_id) {
          this.router.navigate([
            '/graph',
            flow.id,
            'session',
            response.session_id,
          ]);
        } else {
          console.error('Invalid response from run graph API:', response);
        }
      },
      error: (err) => {
        console.error(`Error running flow ${flow.id}`, err);

        // Extract error message from backend response
        let errorMessage = 'Failed to run flow';
        if (err.error && err.error.message) {
          errorMessage = err.error.message;
        } else if (err.error && typeof err.error === 'string') {
          errorMessage = err.error;
        } else if (err.message) {
          errorMessage = err.message;
        }

        this.toastService.error(
          `Error running flow "${flow.name}": ${errorMessage}`
        );
      },
    });
  }
}
