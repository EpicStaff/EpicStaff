import {
  Component,
  Input,
  Output,
  EventEmitter,
  signal,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { CheckboxComponent, LoadingSpinnerComponent, IconButtonComponent } from "@shared/components";
import { FlowSessionStatusBadgeComponent } from './flow-session-status-badge.component';
import {
  GraphSession,
  GraphSessionLight,
  GraphSessionStatus,
} from '../../services/flows-sessions.service';
import { GraphDto } from '../../models/graph.model';
@Component({
  selector: 'app-flow-sessions-table',
  standalone: true,
  imports: [
    CommonModule,
    CheckboxComponent,
    FlowSessionStatusBadgeComponent,
    LoadingSpinnerComponent,
    IconButtonComponent,
  ],
  template: `
    <div class="table-header">
      <div class="search-section"></div>
      <div class="bulk-actions-section">
        <div
          *ngIf="selectedIds().size > 0 && !isLoading && sessions.length > 0"
          class="bulk-actions"
        >
          <button class="delete-btn" (click)="bulkDelete()">
            Delete Selected
          </button>
        </div>
      </div>
    </div>
    <div class="sessions-table-wrapper">
      <table>
        <thead>
          <tr>
            <th>
              <app-checkbox
                [checked]="areAllSelected()"
                [disabled]="isLoading || sessions.length === 0"
                (changed)="toggleSelectAll($event)"
                id="select-all-checkbox"
              ></app-checkbox>
            </th>
            <th>ID</th>
            <th>Status</th>
            <th>Created At</th>
            <th>Finished At</th>
            <th>Actions</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          @if (isLoading) {
          <tr>
            <td colspan="7" style="text-align: center; padding: 40px;">
              <app-loading-spinner size="md" message="Loading sessions..." />
            </td>
          </tr>
          } @else if (showEmptyState) {
          <tr>
            <td colspan="7" style="text-align: center; padding: 40px;">
              <div class="no-sessions-message">
                <p>No sessions found for the selected filters.</p>
                <small
                  >Try adjusting your filter criteria or create a new
                  session.</small
                >
              </div>
            </td>
          </tr>
          } @else {
          <tr *ngFor="let session of sessions; trackBy: trackById">
            <td>
              <app-checkbox
                [checked]="isSelected(session.id)"
                (changed)="toggleSelection(session.id, $event)"
                [id]="'session-checkbox-' + session.id"
              ></app-checkbox>
            </td>
            <td>{{ session.id }}</td>
            <td>
              <app-flow-session-status-badge
                [status]="session.status"
              ></app-flow-session-status-badge>
            </td>
            <td>{{ session.created_at | date : 'medium' }}</td>
            <td>
              {{
                session.finished_at
                  ? (session.finished_at | date : 'medium')
                  : 'Active'
              }}
            </td>
            <td>
              <div class="actions-container">
                <button class="view-btn" (click)="viewSession.emit(session.id)">
                  View
                </button>
                <button
                  *ngIf="canStop(session.status)"
                  class="stop-btn"
                  (click)="stopSession.emit(session.id)"
                  title="Stop session"
                  style="margin-left: 8px;"
                >
                  Stop
                </button>
              </div>
            </td>
            <td>
              <app-icon-button
                icon="ui/x"
                size="1.5rem"
                ariaLabel="Delete session"
                (onClick)="deleteSelected.emit([session.id])"
              ></app-icon-button>
            </td>
          </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styleUrls: ['./flow-sessions-table.component.scss'],
})
export class FlowSessionsTableComponent {
  @Input() sessions: GraphSessionLight[] = [];
  @Input() flow!: GraphDto;
  @Input() isLoading: boolean = false;
  @Input() showEmptyState: boolean = false;

  @Output() deleteSelected = new EventEmitter<number[]>();
  @Output() viewSession = new EventEmitter<number>();
  @Output() stopSession = new EventEmitter<number>();

  public selectedIds = signal<Set<number>>(new Set());

  public readonly GraphSessionStatus = GraphSessionStatus;

  constructor(private readonly cdr: ChangeDetectorRef) {}

  isSelected(id: number) {
    return this.selectedIds().has(id);
  }

  toggleSelection(id: number, checked: boolean) {
    this.selectedIds.update((set) => {
      const s = new Set(set);
      checked ? s.add(id) : s.delete(id);
      return s;
    });
    this.cdr.markForCheck();
  }

  areAllSelected() {
    return (
      this.sessions.length > 0 &&
      this.sessions.every((s) => this.selectedIds().has(s.id))
    );
  }

  toggleSelectAll(checked: boolean) {
    this.selectedIds.set(
      checked ? new Set(this.sessions.map((s) => s.id)) : new Set()
    );
    this.cdr.markForCheck();
  }

  bulkDelete() {
    this.deleteSelected.emit(Array.from(this.selectedIds()));
    this.selectedIds.set(new Set());
    this.cdr.markForCheck();
  }

  canStop(status: GraphSessionStatus) {
    return [
      GraphSessionStatus.RUNNING,
      GraphSessionStatus.WAITING_FOR_USER,
      GraphSessionStatus.PENDING,
    ].includes(status);
  }

  trackById(_: number, item: GraphSessionLight) {
    return item.id;
  }
}
