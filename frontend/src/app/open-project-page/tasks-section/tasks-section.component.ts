import {
  Component,
  OnInit,
  OnDestroy,
  Input,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FullTask } from '../../shared/models/full-task.model';
import { FullAgent } from '../../services/full-agent.service';
import { ProjectStateService } from '../services/project-state.service';
import { Subscription } from 'rxjs';
import { TasksTableComponent } from './tasks-table/tasks-table.component';
import { GetProjectRequest } from '../../features/projects/models/project.model';
import {
  CreateTaskRequest,
  UpdateTaskRequest,
  GetTaskRequest,
} from '../../shared/models/task.model';
import { TasksService } from '../../services/tasks.service'; // Import the TasksService

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
          console.log('Updated agents:', this.agents);
          this.cdr.markForCheck();
        },
        error: (err) => console.error('Error fetching agents:', err),
      })
    );
  }

  ngOnDestroy(): void {
    this.subscription.unsubscribe();
  }
}
