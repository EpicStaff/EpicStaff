import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    EventEmitter,
    inject,
    Input,
    OnInit,
    Output,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { GetProjectRequest } from '../../features/projects/models/project.model';
import { FullAgent } from '../../features/staff/services/full-agent.service';
import { FullTask } from '../../features/tasks/models/full-task.model';
import { TableFullTask } from '../../features/tasks/models/task.model';
import { ProjectStateService } from '../services/project-state.service';
import { TasksTableComponent } from './tasks-table/tasks-table.component';
import { TaskPendingEvent } from './tasks-table/tasks-table.component';

@Component({
    selector: 'app-tasks-section',
    standalone: true,
    templateUrl: './tasks-section.component.html',
    styleUrls: ['./tasks-section.component.scss'],
    imports: [CommonModule, TasksTableComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TasksSectionComponent implements OnInit {
    @Input() project!: GetProjectRequest;
    @Input() isSaving = false;
    @Output() taskPending = new EventEmitter<TaskPendingEvent>();
    @Output() dirtyChange = new EventEmitter<boolean>();
    @Output() autoSaveRequested = new EventEmitter<void>();
    @ViewChild(TasksTableComponent) private table?: TasksTableComponent;

    public tasks: FullTask[] = [];
    public agents: FullAgent[] = [];

    private readonly destroyRef = inject(DestroyRef);

    constructor(
        private projectStateService: ProjectStateService,
        private cdr: ChangeDetectorRef
    ) {}

    ngOnInit(): void {
        this.projectStateService.tasks$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (tasks) => {
                this.tasks = tasks;
                this.cdr.markForCheck();
            },
            error: (err) => console.error('Error fetching tasks:', err),
        });

        this.projectStateService.agents$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (agents) => {
                this.agents = agents;
                this.cdr.markForCheck();
            },
            error: (err) => console.error('Error fetching agents:', err),
        });
    }

    onTaskPending(ev: TaskPendingEvent): void {
        this.taskPending.emit(ev);
    }

    onDirtyChange(isDirty: boolean): void {
        this.dirtyChange.emit(isDirty);
    }

    public validateBeforeSave(): boolean {
        return this.table?.validateBeforeSave() ?? true;
    }

    public clearLocalDirtyAfterSave(): void {
        this.table?.clearLocalDirtyAfterSave();
    }

    public applyCreatedTask(tempRowKey: string, created: { id: number } & Partial<TableFullTask>): void {
        this.table?.applyCreatedTask(tempRowKey, created);
    }

    public applyUpdatedTask(rowKey: string, updated: Partial<TableFullTask>): void {
        this.table?.applyUpdatedTask(rowKey, updated);
    }

    public getCurrentReorderPayload(): Array<{ id: number; order: number }> {
        return this.table?.getCurrentReorderPayload() ?? [];
    }

    public getCurrentRows(): TableFullTask[] {
        return this.table?.getCurrentRows?.() ?? [];
    }

    public stopEditing(): void {
        this.table?.stopEditing();
    }

    public commitPopupIfOpen(): void {
        this.table?.commitPopupIfOpen();
    }
}
