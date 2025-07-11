import { Component, Input, Output, EventEmitter, signal, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { CheckboxComponent } from '../../../../shared/components/form-controls/checkbox/checkbox.component';
import { FlowSessionStatusBadgeComponent } from './flow-session-status-badge.component';
import { GraphSession, GraphSessionStatus } from '../../services/flows-sessions.service';
import { GraphDto } from '../../models/graph.model';
import { FlowSessionStatusFilterDropdownComponent } from './flow-session-status-filter-dropdown.component';

@Component({
  selector: 'app-flow-sessions-table',
  standalone: true,
  imports: [
    CommonModule,
    CheckboxComponent,
    FlowSessionStatusBadgeComponent,
    FlowSessionStatusFilterDropdownComponent
  ],
  template: `
    <div
      style="margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; gap: 12px;"
    >
      <div style="flex: 1; display: flex; align-items: center; gap: 10px;">
        <!-- <input
          type="text"
          placeholder="Search sessions..."
          class="session-search-input"
          [value]="searchQuery"
          (input)="onSearch($event)"
        /> -->
        <app-flow-session-status-filter-dropdown 
            [value]="statusFilter" 
            (valueChange)="onStatusFilterChange($event)">
        </app-flow-session-status-filter-dropdown>
      </div>
      <div style="display: flex; align-items: center; gap: 12px;">
        <div *ngIf="selectedIds().size > 0" class="bulk-actions">
          <button class="delete-btn" (click)="bulkDelete()">Delete Selected</button>
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
                (checkedChange)="toggleSelectAll($event)"
                id="select-all-checkbox"
                label=""
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
          <tr *ngFor="let session of sessions; trackBy: trackById">
            <td>
              <app-checkbox
                [checked]="isSelected(session.id)"
                (checkedChange)="toggleSelection(session.id, $event)"
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
              <button
                class="icon-btn delete-icon-btn"
                (click)="deleteSelected.emit([session.id])"
                title="Delete session"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  class="icon icon-tabler icon-tabler-x"
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  stroke-width="2"
                  stroke="currentColor"
                  fill="none"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styleUrls: ['./flow-sessions-table.component.scss'],
})
export class FlowSessionsTableComponent {
  @Input() sessions: GraphSession[] = [];
  @Input() flow!: GraphDto;
  @Input() statusFilter: string[] = [];

  @Output() deleteSelected = new EventEmitter<number[]>();
  @Output() viewSession = new EventEmitter<number>();
  @Output() stopSession = new EventEmitter<number>();
  @Output() statusFilterChanged = new EventEmitter<string[]>();

  public selectedIds = signal<Set<number>>(new Set());

  public readonly GraphSessionStatus = GraphSessionStatus;

  constructor(private cdr: ChangeDetectorRef) { }

  // row-selection
  isSelected(id: number) {
    return this.selectedIds().has(id);
  }

  toggleSelection(id: number, checked: boolean) {
    this.selectedIds.update(set => {
      const s = new Set(set);
      checked ? s.add(id) : s.delete(id);
      return s;
    });
    this.cdr.markForCheck();
  }

  areAllSelected() {
    return this.sessions.length > 0
      && this.sessions.every(s => this.selectedIds().has(s.id));
  }

  toggleSelectAll(checked: boolean) {
    this.selectedIds.set(
      checked
        ? new Set(this.sessions.map(s => s.id))
        : new Set()
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
      GraphSessionStatus.PENDING
    ].includes(status);
  }

  onStatusFilterChange(values: string[]) {
    this.statusFilterChanged.emit(values);
  }

  trackById(_: number, item: GraphSession) {
    return item.id;
  }
}
