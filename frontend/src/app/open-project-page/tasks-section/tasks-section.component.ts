import {
  Component,
  OnInit,
  OnDestroy,
  Input,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Output,
  EventEmitter,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FullTask } from '../../features/tasks/models/full-task.model';
import { FullAgent } from '../../features/staff/services/full-agent.service';
import { ProjectStateService } from '../services/project-state.service';
import { Subscription } from 'rxjs';
import { TasksTableComponent } from './tasks-table/tasks-table.component';
import { GetProjectRequest } from '../../features/projects/models/project.model';
import {
  CreateTaskRequest,
  UpdateTaskRequest,
  GetTaskRequest,
} from '../../features/tasks/models/task.model';
import { TaskPendingEvent } from './tasks-table/tasks-table.component';
import { TasksService } from '../../features/tasks/services/tasks.service';

@Component({
  selector: 'app-tasks-section',
  standalone: true,
  templateUrl: './tasks-section.component.html',
  styleUrls: ['./tasks-section.component.scss'],
  imports: [CommonModule, TasksTableComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TasksSectionComponent implements OnInit, OnDestroy {
  @Input() project!: GetProjectRequest;
  @Input() isSaving = false;
  @Output() taskPending = new EventEmitter<TaskPendingEvent>();
  @Output() dirtyChange = new EventEmitter<boolean>();
  @ViewChild(TasksTableComponent) private table?: TasksTableComponent;

  public tasks: FullTask[] = [];
  public agents: FullAgent[] = [];

  private subscription = new Subscription();

  constructor(
    private projectStateService: ProjectStateService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.subscription.add(
      this.projectStateService.tasks$.subscribe({
        next: (tasks) => {
          this.tasks = tasks;
          this.cdr.markForCheck();
        },
        error: (err) => console.error('Error fetching tasks:', err),
      })
    );

    this.subscription.add(
      this.projectStateService.agents$.subscribe({
        next: (agents) => {
          this.agents = agents;
          this.cdr.markForCheck();
        },
        error: (err) => console.error('Error fetching agents:', err),
      })
    );
  }

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
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

  public applyCreatedTask(tempRowKey: string, created: any): void {
    this.table?.applyCreatedTask(tempRowKey, created);
  }

  public applyUpdatedTask(rowKey: string, updated: any): void {
    this.table?.applyUpdatedTask(rowKey, updated);
  }

  public getCurrentReorderPayload(): Array<{ id: number; order: number }> {
    return this.table?.getCurrentReorderPayload() ?? [];
  }

  public getCurrentRows(): any[] {
    return this.table?.getCurrentRows?.() ?? [];
  }
}
