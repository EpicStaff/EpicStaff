import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  input,
  OnDestroy,
  OnInit,
  signal,
  Type,
  Input,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HeaderComponent } from './header/header.component';
import { DetailsContentComponent } from './details-content/details-content.component';
import { VariablesContentComponent } from './variables-content/variables-content.component';
import { AgentsSectionComponent } from './agents-section/agents-section.component';
import { TasksSectionComponent } from './tasks-section/tasks-section.component';
import { SettingsSectionComponent } from './settings-section/settings-section.component';
import { FormsModule } from '@angular/forms';
import { ProjectsStorageService } from '../features/projects/services/projects-storage.service';
import { TasksService } from '../services/tasks.service';
import { finalize, forkJoin, Subscription } from 'rxjs';
import { GetProjectRequest } from '../features/projects/models/project.model';
import { Dialog } from '@angular/cdk/dialog';
import { FullTask } from '../shared/models/full-task.model';
import { FullAgentService, FullAgent } from '../services/full-agent.service';
import { FullTaskService } from '../services/full-task.service';
import { ProjectStateService } from './services/project-state.service';
import {
  trigger,
  state,
  style,
  animate,
  transition,
} from '@angular/animations';
import { ToastService } from '../services/notifications/toast.service';
import { SpinnerComponent } from '../shared/components/spinner/spinner.component';
import { FlowGraphComponent } from '../visual-programming/flow-graph/flow-graph.component';
import { ActivatedRoute } from '@angular/router';
import { CreateAgentFormComponent } from '../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';

// Improved animations that work properly with content visibility
export const expandCollapseAnimation = trigger('expandCollapse', [
  state(
    'collapsed',
    style({
      height: '0',
      opacity: '0',
      visibility: 'hidden',
    })
  ),
  state(
    'expanded',
    style({
      height: '*',
      opacity: '1',
      visibility: 'visible',
    })
  ),
  transition('expanded => collapsed', [
    animate('225ms cubic-bezier(0.4, 0.0, 0.2, 1)'),
  ]),
  transition('collapsed => expanded', [
    animate('225ms cubic-bezier(0.4, 0.0, 0.2, 1)'),
  ]),
]);

// Interface for section configuration
interface SectionConfig {
  id: string;
  title: string;
  component: Type<any>;
  inputs?: Record<string, any>;
  showCount?: boolean;
  count?: number;
  showAddButton?: boolean;
}

// Type for tabs
type TabType = 'overview' | 'draft';

// Flow model interface
interface FlowModel {
  nodes: any[];
  connections: any[];
  groups: any[];
}

@Component({
  selector: 'app-open-project-page',
  standalone: true,
  templateUrl: './open-project-page.component.html',
  styleUrl: './open-project-page.component.scss',
  imports: [
    CommonModule,

    HeaderComponent,

    SettingsSectionComponent,
    FormsModule,
    SpinnerComponent,
  ],
  animations: [expandCollapseAnimation],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [ProjectStateService],
})
export class OpenProjectPageComponent implements OnInit, OnDestroy {
  @Input() showHeader: boolean = true;
  @Input() inputProjectId?: string | number;

  public projectId!: string;
  public project!: GetProjectRequest;
  private subscription = new Subscription();
  public isLoading = signal(true);

  public activeTab: TabType = 'overview';

  public mockFlowData: FlowModel = {
    nodes: [],
    connections: [],
    groups: [],
  };

  public expandedSections = new Set<string>();

  public sections: SectionConfig[] = [];

  constructor(
    private projectsService: ProjectsStorageService,
    private tasksService: TasksService,
    private cdr: ChangeDetectorRef,
    private fullAgentService: FullAgentService,
    private fullTaskService: FullTaskService,
    public projectStateService: ProjectStateService,
    private toastService: ToastService,
    private route: ActivatedRoute,
    private dialog: Dialog
  ) {}

  ngOnInit() {
    if (this.inputProjectId) {
      this.projectId = String(this.inputProjectId);
      console.log('ngOnInit - using input projectId:', this.projectId);
      this.loadData();
    } else {
      this.projectId = this.route.snapshot.paramMap.get('projectId')!;
      console.log('ngOnInit - projectId from route:', this.projectId);

      if (!this.projectId) {
        console.error('No projectId found in route params or input!');
        this.toastService.error('Project ID not found');
        this.isLoading.set(false);
        return;
      }

      this.loadData();
    }
  }

  // Set active tab
  setActiveTab(tab: TabType): void {
    if (this.activeTab !== tab) {
      this.activeTab = tab;
      this.cdr.markForCheck();
    }
  }

  private setupSections() {
    this.sections = [
      {
        id: 'details',
        title: 'Details',
        component: DetailsContentComponent,
        inputs: {
          description: this.project.description ?? '',
        },
      },

      {
        id: 'agents',
        title: 'Agents',
        component: AgentsSectionComponent,
        showCount: true,
        count: this.projectStateService.agentCount(),
        showAddButton: true,
      },
      {
        id: 'tasks',
        title: 'Tasks',
        component: TasksSectionComponent,
        inputs: {
          project: this.project,
        },
        showCount: true,
        count: this.projectStateService.taskCount(),
        showAddButton: false,
      },
      {
        id: 'settings',
        title: 'Settings',
        component: SettingsSectionComponent,
        inputs: {
          project: this.project,
        },
        // We'll handle the output binding separately in the template
      },
    ];
  }

  private loadData(): void {
    const loadStartTime = Date.now();
    this.isLoading.set(true);

    console.log('loadData - Starting to load project with ID:', this.projectId);

    const projectRequest = this.projectsService.getProjectById(+this.projectId);

    const tasksRequest = this.fullTaskService.getFullTasksByProject(
      +this.projectId
    );
    const agentsRequest = this.fullAgentService.getFullAgentsByProject(
      +this.projectId
    );

    const combinedRequest = forkJoin({
      project: projectRequest,
      tasks: tasksRequest,
      agents: agentsRequest,
    });

    this.subscription.add(
      combinedRequest
        .pipe(
          finalize(() => {
            // Ensure minimum loading time of 500ms
            const loadTime = Date.now() - loadStartTime;
            const remainingTime = Math.max(0, 500 - loadTime);

            setTimeout(() => {
              console.log('loadData - Finalizing, setting isLoading to false');
              this.isLoading.set(false);
              if (this.project) {
                this.setupSections();
              }
              this.cdr.markForCheck();
            }, remainingTime);
          })
        )
        .subscribe({
          next: ({ project, tasks, agents }) => {
            console.log('loadData - Success! Project:', project);
            console.log('loadData - Tasks:', tasks);
            console.log('loadData - Agents:', agents);

            this.projectStateService.setProject(project ?? null);

            if (!project) {
              throw new Error(
                `Project with ID ${this.projectId} not found or essential data is missing.`
              );
            }
            this.project = project;
            console.log('project', this.project);

            this.projectStateService.updateTasks(tasks);
            this.projectStateService.updateAgents(agents);

            this.cdr.markForCheck();
          },
          error: (err) => {
            console.error('loadData - Failed to fetch project data', err);
            console.error('Error details:', err.message, err.status);
            this.toastService.error('Failed to load project data');
            this.isLoading.set(false);
            this.cdr.markForCheck();
          },
        })
    );
  }

  // Check if a section is expanded
  isSectionExpanded(sectionId: string): boolean {
    return this.expandedSections.has(sectionId);
  }

  // Toggle section expansion (now allows multiple open sections)
  toggleSection(sectionId: string): void {
    if (this.expandedSections.has(sectionId)) {
      this.expandedSections.delete(sectionId);
    } else {
      this.expandedSections.add(sectionId);
    }

    this.cdr.markForCheck();
  }

  onAddAction(event: MouseEvent, sectionId: string) {
    // Prevent the section from toggling
    event.stopPropagation();

    // Handle add action based on section ID
    if (sectionId === 'agents') {
      console.log('Add agent clicked');

      // Open create agent dialog
      const dialogRef = this.dialog.open<FullAgent>(CreateAgentFormComponent, {
        width: '600px',
        data: {
          isEditMode: false,
          projectId: this.project.id,
        },
      });

      // Handle dialog result
      dialogRef.closed.subscribe((newAgent) => {
        if (newAgent) {
          this.projectStateService.addAgent(newAgent);

          this.setupSections();
          this.cdr.markForCheck();
        }
      });
    } else if (sectionId === 'tasks') {
      console.log('Add task clicked');
    }
  }

  onSettingsChanged(updatedSettings: Partial<GetProjectRequest>) {
    console.log(
      '🎯 Parent component received settings change:',
      updatedSettings
    );

    const keys = Object.keys(
      updatedSettings
    ) as (keyof Partial<GetProjectRequest>)[];

    // Log the updated settings object
    console.log('Updated settings received:', updatedSettings);

    keys.forEach((key) => {
      const updatedValue = updatedSettings[key];

      // Log each setting change
      console.log(
        `Setting change detected: Key: ${key}, Value: ${updatedValue}`
      );

      if (updatedValue !== undefined) {
        this.updateProjectSetting(key, updatedValue);
      }
    });
  }

  private updateProjectSetting(key: string, value: any) {
    // Create patch data with only the changed field
    const patchData = { [key]: value };

    // Log the patch data
    console.log(`Sending patch update for ${key} with new value:`, value);

    // Send PATCH request with only the changed field
    this.projectsService
      .patchUpdateProject(this.project.id, patchData)
      .subscribe({
        next: (updatedProject) => {
          console.log('🔥 PATCH Response received:', updatedProject);
          console.log('🔥 Current project before update:', this.project);
          console.log('🔥 Memory field in response:', updatedProject.memory);

          // Update local component state with the response
          this.project = updatedProject;

          // Update ProjectStateService with the latest project data
          this.projectStateService.setProject(updatedProject);

          // Debug: Check current cache state before update
          const currentCachedProject = this.projectsService
            .projects()
            .find((p) => p.id === updatedProject.id);
          console.log(
            '🔥 Project in cache BEFORE update:',
            currentCachedProject
          );

          // Explicitly update the ProjectsStorageService cache to ensure consistency
          this.projectsService.updateProjectInCache(updatedProject);

          // Debug: Check cache state after update
          const updatedCachedProject = this.projectsService
            .projects()
            .find((p) => p.id === updatedProject.id);
          console.log(
            '🔥 Project in cache AFTER update:',
            updatedCachedProject
          );
          console.log(
            '🔥 Memory field in cache after update:',
            updatedCachedProject?.memory
          );

          // Trigger change detection
          this.cdr.markForCheck();

          this.toastService.success('Project updated successfully');
          console.log('Project updated successfully:', updatedProject);
        },
        error: (error) => {
          // Log the error if the update fails
          console.error(`Error updating project field ${key}:`, error);

          // Extract error message for user feedback
          let errorMessage = 'Failed to update project';
          if (error.error && error.error.message) {
            errorMessage = error.error.message;
          } else if (error.error && typeof error.error === 'string') {
            errorMessage = error.error;
          } else if (error.message) {
            errorMessage = error.message;
          }

          this.toastService.error(`Error updating project: ${errorMessage}`);
        },
      });
  }

  ngOnDestroy() {
    // Unsubscribe from all subscriptions to prevent memory leaks
    this.projectStateService.setProject(null);
    this.subscription.unsubscribe();
  }
}
