import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnDestroy,
    Output,
    signal,
    SimpleChanges,
} from '@angular/core';
import { Router } from '@angular/router';
import { CheckboxComponent, IconButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { GraphMessagesComponent } from 'src/app/pages/running-graph/components/graph-messages/graph-messages.component';

import { GraphDto } from '../../models/graph.model';
import {
    DurationFilter,
    GraphSessionLight,
    GraphSessionStatus,
    isTerminalSessionStatus,
} from '../../services/flows-sessions.service';
import { DurationFilterDropdownComponent } from './duration-filter-dropdown.component';
import { FlowNameFilterDropdownComponent } from './flow-name-filter-dropdown.component';
import { FlowSessionStatusBadgeComponent } from './flow-session-status-badge.component';
import { FlowSessionStatusFilterDropdownComponent } from './flow-session-status-filter-dropdown.component';
@Component({
    selector: 'app-flow-sessions-table',
    standalone: true,
    imports: [
        CommonModule,
        CheckboxComponent,
        FlowSessionStatusBadgeComponent,
        LoadingSpinnerComponent,
        IconButtonComponent,
        GraphMessagesComponent,
        FlowSessionStatusFilterDropdownComponent,
        FlowNameFilterDropdownComponent,
        DurationFilterDropdownComponent,
    ],
    template: `
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
                        <th>
                            <app-flow-session-status-filter-dropdown
                                [value]="statusFilter"
                                (valueChange)="statusFilterChange.emit($event)"
                            >
                            </app-flow-session-status-filter-dropdown>
                        </th>
                        <th *ngIf="showFlowName">
                            <app-flow-name-filter-dropdown
                                [flows]="flows"
                                [value]="flowNameFilter"
                                (valueChange)="flowNameFilterChange.emit($event)"
                            ></app-flow-name-filter-dropdown>
                        </th>
                        <th
                            [class.sortable]="sortable"
                            (click)="sortable && toggleSort()"
                        >
                            Created At
                            @if (sortable) {
                                <span class="sort-icon">{{ sortOrder === 'asc' ? '↑' : '↓' }}</span>
                            }
                        </th>
                        <th>
                            @if (showDuration) {
                                <app-duration-filter-dropdown
                                    [value]="durationFilter"
                                    (valueChange)="durationFilterChange.emit($event)"
                                ></app-duration-filter-dropdown>
                            } @else {
                                Finished At
                            }
                        </th>
                        <th
                            style="text-align: center"
                            class="actions"
                        >
                            Actions
                        </th>
                    </tr>
                </thead>
                <tbody>
                    @if (isLoading) {
                        <tr>
                            <td
                                [attr.colspan]="showFlowName ? 7 : 6"
                                style="text-align: center; padding: 40px;"
                            >
                                <app-loading-spinner
                                    size="md"
                                    message="Loading sessions..."
                                />
                            </td>
                        </tr>
                    } @else if (showEmptyState) {
                        <tr>
                            <td
                                [attr.colspan]="showFlowName ? 7 : 6"
                                style="text-align: center; padding: 40px;"
                            >
                                <div class="no-sessions-message">
                                    <p>No sessions found for the selected filters.</p>
                                    <small>Try adjusting your filter criteria or create a new session.</small>
                                </div>
                            </td>
                        </tr>
                    } @else {
                        <ng-container *ngFor="let session of sessions; trackBy: trackById">
                            <tr [class.row-expanded]="!externalPreview && expandedSessionId() === session.id">
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
                                <td
                                    *ngIf="showFlowName"
                                    class="flow-link-td"
                                >
                                    <a
                                        class="flow-link"
                                        (click)="navigateToFlow(session.graph_id)"
                                    >
                                        {{ session.graph_name }}
                                    </a>
                                </td>

                                <td>{{ session.created_at | date: 'medium' }}</td>
                                <td>
                                    @if (showDuration) {
                                        {{ getDuration(session) }}
                                    } @else {
                                        {{ session.finished_at ? (session.finished_at | date: 'medium') : 'Active' }}
                                    }
                                </td>
                                <td>
                                    <div class="actions-container">
                                        <button
                                            class="view-btn"
                                            [class.view-btn--active]="expandedSessionId() === session.id"
                                            (click)="togglePreview(session.id)"
                                        >
                                            {{ expandedSessionId() === session.id ? 'Hide' : 'Preview' }}
                                        </button>
                                        <img
                                            src="assets/icons/ui/session-arrow.svg"
                                            alt="arrow-icon"
                                            class="arrow-icon"
                                            (click)="viewSession.emit(session.id)"
                                        />
                                        <img
                                            src="assets/icons/ui/stop-session.svg"
                                            alt="arrow-icon"
                                            *ngIf="canStop(session.status)"
                                            (click)="stopSession.emit(session.id)"
                                            title="Stop session"
                                            style="margin-left: 8px;"
                                            class="arrow-icon"
                                        />
                                        <app-icon-button
                                            *ngIf="!canStop(session.status)"
                                            icon="x"
                                            size="1.5rem"
                                            ariaLabel="Delete session"
                                            (onClick)="deleteSelected.emit([session.id])"
                                        ></app-icon-button>
                                    </div>
                                </td>
                            </tr>

                            <tr
                                *ngIf="!externalPreview && expandedSessionId() === session.id"
                                class="preview-row"
                            >
                                <td
                                    [attr.colspan]="showFlowName ? 7 : 6"
                                    class="preview-cell"
                                >
                                    <div class="preview-content">
                                        <app-graph-messages
                                            [graphId]="flow?.id ?? session.graph_id"
                                            [sessionId]="session.id.toString()"
                                            [compact]="true"
                                        ></app-graph-messages>
                                    </div>
                                </td>
                            </tr>
                        </ng-container>
                    }
                </tbody>
            </table>
        </div>
    `,
    styleUrls: ['./flow-sessions-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowSessionsTableComponent implements OnChanges, OnDestroy {
    @Input() sessions: GraphSessionLight[] = [];
    @Input() flow?: GraphDto;
    @Input() isLoading: boolean = false;
    @Input() showEmptyState: boolean = false;
    @Input() showFlowName: boolean = false;
    @Input() showDuration: boolean = false;
    @Input() sortable: boolean = false;
    @Input() sortOrder: 'asc' | 'desc' = 'desc';
    @Input() statusFilter: string[] = ['all'];

    @Input() selectedIds: Set<number> = new Set();
    @Input() flows: { id: number; name: string }[] = [];
    @Input() flowNameFilter: string | null = null;
    @Input() durationFilter: DurationFilter | null = null;

    @Input() externalPreview: boolean = false;
    @Input() activePreviewId: number | null = null;

    @Output() deleteSelected = new EventEmitter<number[]>();
    @Output() viewSession = new EventEmitter<number>();
    @Output() stopSession = new EventEmitter<number>();
    @Output() sortChange = new EventEmitter<'asc' | 'desc'>();
    @Output() statusFilterChange = new EventEmitter<string[]>();
    @Output() flowNameFilterChange = new EventEmitter<string | null>();
    @Output() durationFilterChange = new EventEmitter<DurationFilter | null>();
    @Output() selectedIdsChange = new EventEmitter<Set<number>>();
    @Output() previewSession = new EventEmitter<number | null>();

    public expandedSessionId = signal<number | null>(null);

    public readonly GraphSessionStatus = GraphSessionStatus;

    private durationInterval: ReturnType<typeof setInterval> | null = null;

    constructor(
        private readonly cdr: ChangeDetectorRef,
        private router: Router
    ) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['sessions'] || changes['showDuration']) {
            this.manageDurationInterval();
        }
        if (changes['activePreviewId'] && this.externalPreview) {
            this.expandedSessionId.set(this.activePreviewId);
            this.cdr.markForCheck();
        }
    }

    public ngOnDestroy(): void {
        if (this.durationInterval) {
            clearInterval(this.durationInterval);
            this.durationInterval = null;
        }
    }

    private manageDurationInterval(): void {
        const needsTimer = this.showDuration && this.sessions.some((s) => s.finished_at === null);
        if (needsTimer && !this.durationInterval) {
            this.durationInterval = setInterval(() => this.cdr.markForCheck(), 1000);
        } else if (!needsTimer && this.durationInterval) {
            clearInterval(this.durationInterval);
            this.durationInterval = null;
        }
    }

    public navigateToFlow(graphId: number): void {
        this.router.navigate(['/flows', graphId]);
    }

    public togglePreview(sessionId: number): void {
        const newId = this.expandedSessionId() === sessionId ? null : sessionId;
        this.expandedSessionId.set(newId);
        if (this.externalPreview) {
            this.previewSession.emit(newId);
        }
        this.cdr.markForCheck();
    }

    isSelected(id: number): boolean {
        return this.selectedIds.has(id);
    }

    toggleSelection(id: number, checked: boolean): void {
        const next = new Set(this.selectedIds);
        checked ? next.add(id) : next.delete(id);
        this.selectedIdsChange.emit(next);
        this.cdr.markForCheck();
    }

    areAllSelected(): boolean {
        return this.sessions.length > 0 && this.sessions.every((s) => this.selectedIds.has(s.id));
    }

    toggleSelectAll(checked: boolean): void {
        const next = new Set(this.selectedIds);
        if (checked) {
            this.sessions.forEach((s) => next.add(s.id));
        } else {
            this.sessions.forEach((s) => next.delete(s.id));
        }
        this.selectedIdsChange.emit(next);
        this.cdr.markForCheck();
    }

    canStop(status: GraphSessionStatus) {
        return !isTerminalSessionStatus(status);
    }

    trackById(_: number, item: GraphSessionLight) {
        return item.id;
    }

    public toggleSort(): void {
        this.sortChange.emit(this.sortOrder === 'desc' ? 'asc' : 'desc');
    }

    public getDuration(session: GraphSessionLight): string {
        const start = new Date(session.created_at).getTime();
        const end = session.finished_at ? new Date(session.finished_at).getTime() : Date.now();
        const diffMs = Math.max(0, end - start);
        const totalSeconds = Math.floor(diffMs / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (hours > 0) return `${hours}h ${minutes}m`;
        if (minutes > 0) return `${minutes}m ${seconds}s`;
        return `${seconds}s`;
    }
}
