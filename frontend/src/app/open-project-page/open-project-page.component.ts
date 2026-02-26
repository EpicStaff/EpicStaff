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
import { TasksService } from '../features/tasks/services/tasks.service';
import { finalize, forkJoin, Subscription } from 'rxjs';
import { GetProjectRequest } from '../features/projects/models/project.model';
import { Dialog } from '@angular/cdk/dialog';
import { FullTask } from '../features/tasks/models/full-task.model';
import { FullAgentService, FullAgent } from '../features/staff/services/full-agent.service';
import { FullTaskService } from './services/full-task.service';
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

        // Subscribe to state changes to trigger change detection
        this.subscription.add(
            this.projectStateService.agents$.subscribe(() => {
                this.cdr.markForCheck();
            })
        );

        this.subscription.add(
            this.projectStateService.tasks$.subscribe(() => {
                this.cdr.markForCheck();
            })
        );
    }

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
                    projectId: this.project.id,
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
            },
        ];
    }

    // Get reactive count for agents
    getAgentCount(): number {
        return this.projectStateService.agentCount();
    }

    // Get reactive count for tasks
    getTaskCount(): number {
        return this.projectStateService.taskCount();
    }

    private loadData(): void {
        const loadStartTime = Date.now();
        this.isLoading.set(true);

        console.log(
            'loadData - Starting to load project with ID:',
            this.projectId
        );

        const projectRequest = this.projectsService.getProjectById(
            +this.projectId
        );

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
                            console.log(
                                'loadData - Finalizing, setting isLoading to false'
                            );
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
                        console.error(
                            'loadData - Failed to fetch project data',
                            err
                        );
                        console.error(
                            'Error details:',
                            err.message,
                            err.status
                        );
                        this.toastService.error('Failed to load project data');
                        this.isLoading.set(false);
                        this.cdr.markForCheck();
                    },
                })
        );
    }

    isSectionExpanded(sectionId: string): boolean {
        return this.expandedSections.has(sectionId);
    }

    toggleSection(sectionId: string): void {
        if (this.expandedSections.has(sectionId)) {
            this.expandedSections.delete(sectionId);
        } else {
            this.expandedSections.add(sectionId);
        }

        this.cdr.markForCheck();
    }

    onAddAction(event: MouseEvent, sectionId: string) {
        event.stopPropagation();

        if (sectionId === 'agents') {
            console.log('Add agent clicked');

            const dialogRef = this.dialog.open<FullAgent>(
                CreateAgentFormComponent,
                {
                    data: {
                        isEditMode: false,
                        projectId: this.project.id,
                    },
                }
            );

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

    onSettingsChanged(formValue: Partial<GetProjectRequest>) {
        console.log(
            '🎯 Parent component received reactive form value:',
            formValue
        );

        // Convert form value to the format expected by the API
        const updateData: Partial<GetProjectRequest> = {};

        // Handle each field from the form
        if (formValue.memory !== undefined) {
            updateData.memory = formValue.memory;
        }
        if (formValue.cache !== undefined) {
            updateData.cache = formValue.cache;
        }
        if (formValue.process !== undefined) {
            updateData.process = formValue.process;
        }
        if (formValue.max_rpm !== undefined) {
            updateData.max_rpm = formValue.max_rpm;
        }
        if (formValue.similarity_threshold !== undefined) {
            updateData.similarity_threshold =
                formValue.similarity_threshold?.toString();
        }
        if (formValue.search_limit !== undefined) {
            updateData.search_limit = formValue.search_limit;
        }
        if (formValue.manager_llm_config !== undefined) {
            updateData.manager_llm_config = formValue.manager_llm_config;
        }
        if (formValue.memory_llm_config !== undefined) {
            updateData.memory_llm_config = formValue.memory_llm_config;
        }
        if (formValue.embedding_config !== undefined) {
            updateData.embedding_config = formValue.embedding_config;
        }

        console.log('Processed update data:', updateData);

        // Send the update request with all changed values
        if (Object.keys(updateData).length > 0) {
            this.updateProjectSettings(updateData);
        }
    }

    private updateProjectSettings(updateData: Partial<GetProjectRequest>) {
        console.log('Sending batch update with data:', updateData);

        this.projectsService
            .patchUpdateProject(this.project.id, updateData)
            .subscribe({
                next: (updatedProject) => {
                    this.project = updatedProject;
                    this.projectStateService.setProject(updatedProject);

                    // Update cache
                    this.projectsService.updateProjectInCache(updatedProject);

                    this.cdr.markForCheck();
                    this.toastService.success(
                        'Project settings updated successfully'
                    );
                    console.log(
                        'Project updated successfully:',
                        updatedProject
                    );
                },
                error: (error) => {
                    console.error('Error updating project settings:', error);

                    let errorMessage = 'Failed to update project settings';
                    if (error.error && error.error.message) {
                        errorMessage = error.error.message;
                    } else if (error.error && typeof error.error === 'string') {
                        errorMessage = error.error;
                    } else if (error.message) {
                        errorMessage = error.message;
                    }

                    this.toastService.error(
                        `Error updating project: ${errorMessage}`
                    );
                },
            });
    }

    ngOnDestroy() {
        this.projectStateService.setProject(null);
        this.subscription.unsubscribe();
    }
}
