/* eslint-disable @typescript-eslint/no-explicit-any */
import { animate, state, style, transition, trigger } from '@angular/animations';
import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    HostListener,
    Input,
    OnDestroy,
    OnInit,
    signal,
    Type,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { EMPTY, filter, forkJoin, from, Observable, of, Subscription } from 'rxjs';
import { catchError, concatMap, finalize, map, switchMap, tap, toArray } from 'rxjs/operators';

import { CanComponentDeactivate } from '../core/guards/unsaved-changes.guard';
import { GetProjectRequest } from '../features/projects/models/project.model';
import { ProjectsStorageService } from '../features/projects/services/projects-storage.service';
import { CreateAgentRequest } from '../features/staff/models/agent.model';
import { FullAgent, FullAgentService } from '../features/staff/services/full-agent.service';
import { AgentsService } from '../features/staff/services/staff.service';
import { TasksService } from '../features/tasks/services/tasks.service';
import { ToastService } from '../services/notifications/toast.service';
import { CreateAgentFormComponent } from '../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';
import { SpinnerComponent } from '../shared/components/spinner/spinner.component';
import { UnsavedChangesDialogService } from '../shared/components/unsaved-changes-dialog/unsaved-changes-dialog.service';
import { AgentsSectionComponent } from './agents-section/agents-section.component';
import { DetailsContentComponent } from './details-content/details-content.component';
import { HeaderComponent } from './header/header.component';
import { FullTaskService } from './services/full-task.service';
import { ProjectStateService } from './services/project-state.service';
import { SettingsSectionComponent } from './settings-section/settings-section.component';
import { TasksSectionComponent } from './tasks-section/tasks-section.component';
import { TaskPendingEvent } from './tasks-section/tasks-table/tasks-table.component';

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
    transition('expanded => collapsed', [animate('225ms cubic-bezier(0.4, 0.0, 0.2, 1)')]),
    transition('collapsed => expanded', [animate('225ms cubic-bezier(0.4, 0.0, 0.2, 1)')]),
]);

// Interface for section configuration
interface SectionConfig {
    id: string;
    title: string;
    component: Type<unknown>;
    inputs?: Record<string, unknown>;
    showCount?: boolean;
    count?: number;
    showAddButton?: boolean;
}

// Type for tabs
type TabType = 'overview' | 'draft';

// Flow model interface
interface FlowModel {
    nodes: unknown[];
    connections: unknown[];
    groups: unknown[];
}

function asTaskPendingPayloadRecord(payload: unknown): Record<string, unknown> {
    if (payload !== null && typeof payload === 'object' && !Array.isArray(payload)) {
        return payload as Record<string, unknown>;
    }
    return {};
}

@Component({
    selector: 'app-open-project-page',
    templateUrl: './open-project-page.component.html',
    styleUrl: './open-project-page.component.scss',
    imports: [
        CommonModule,

        HeaderComponent,
        DetailsContentComponent,
        AgentsSectionComponent,
        TasksSectionComponent,

        SettingsSectionComponent,
        FormsModule,
        SpinnerComponent,
    ],
    animations: [expandCollapseAnimation],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [ProjectStateService],
})
export class OpenProjectPageComponent implements OnInit, OnDestroy, CanComponentDeactivate {
    @Input() showHeader: boolean = true;
    @Input() inputProjectId?: string | number;
    @ViewChild(TasksSectionComponent) private tasksSection?: TasksSectionComponent;

    public projectId!: string;
    public project!: GetProjectRequest;
    private subscription = new Subscription();
    public isLoading = signal(true);
    public readonly agentCount = computed(() => this.projectStateService.agentCount());
    public readonly taskCount = computed(() => this.projectStateService.taskCount());

    public activeTab: TabType = 'overview';

    public hasUnsavedChanges = false;
    public isSaving = false;

    private pendingProjectUpdate: Partial<GetProjectRequest> | null = null;
    private pendingAgentUpdates = new Map<number, FullAgent>();
    private baselineAgentsById = new Map<number, FullAgent>();
    public pendingTaskUpdates = new Map<string, TaskPendingEvent>();
    private suppressNextSettingsEmit = false;

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
        private dialog: Dialog,
        private agentsService: AgentsService,
        private unsavedChangesDialog: UnsavedChangesDialogService,
        private destroyRef: DestroyRef
    ) {}

    ngOnInit() {
        if (this.inputProjectId) {
            this.projectId = String(this.inputProjectId);
            this.loadData();
        } else {
            this.projectId = this.route.snapshot.paramMap.get('projectId')!;

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

    private loadData(): void {
        const loadStartTime = Date.now();
        this.isLoading.set(true);

        const projectRequest = this.projectsService.getProjectById(+this.projectId);

        const tasksRequest = this.fullTaskService.getFullTasksByProject(+this.projectId);
        const agentsRequest = this.fullAgentService.getFullAgentsByProject(+this.projectId);

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
                        this.projectStateService.setProject(project ?? null);

                        if (!project) {
                            throw new Error(
                                `Project with ID ${this.projectId} not found or essential data is missing.`
                            );
                        }
                        this.project = project;

                        this.projectStateService.updateTasks(tasks);
                        this.projectStateService.updateAgents(agents);

                        this.baselineAgentsById = new Map(
                            (agents ?? []).map((a: any) => [Number(a.id), structuredClone(a)])
                        );

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

            const dialogRef = this.dialog.open<{ kind: 'create' | 'update'; payload: CreateAgentRequest }>(
                CreateAgentFormComponent,
                {
                    data: {
                        isEditMode: false,
                        projectId: this.project.id,
                    },
                }
            );

            dialogRef.closed
                .pipe(
                    takeUntilDestroyed(this.destroyRef),
                    filter(
                        (result): result is { kind: 'create'; payload: CreateAgentRequest } =>
                            !!result && result.kind === 'create'
                    ),
                    switchMap((result) =>
                        this.agentsService.createAgent(result.payload).pipe(
                            catchError(() => {
                                this.toastService.error('Failed to create agent');
                                return EMPTY;
                            })
                        )
                    )
                )
                .subscribe();
        } else if (sectionId === 'tasks') {
            console.log('Add task clicked');
        }
    }

    onSettingsChanged(formValue: Partial<GetProjectRequest>) {
        if (!this.project) return;

        const updateData: Partial<GetProjectRequest> = {};

        if (formValue.memory !== undefined) updateData.memory = formValue.memory;
        if (formValue.cache !== undefined) updateData.cache = formValue.cache;
        if (formValue.process !== undefined) updateData.process = formValue.process;
        if (formValue.max_rpm !== undefined) updateData.max_rpm = formValue.max_rpm;
        if (formValue.manager_llm_config !== undefined) updateData.manager_llm_config = formValue.manager_llm_config;
        if (formValue.memory_llm_config !== undefined) updateData.memory_llm_config = formValue.memory_llm_config;
        if (formValue.embedding_config !== undefined) updateData.embedding_config = formValue.embedding_config;
        if ((formValue as any).default_temperature !== undefined)
            (updateData as any).default_temperature = (formValue as any).default_temperature;

        const nextPending: Partial<GetProjectRequest> = {
            ...(this.pendingProjectUpdate ?? {}),
        };

        for (const [key, nextRaw] of Object.entries(updateData) as Array<[keyof GetProjectRequest, any]>) {
            const next = this.normalizeSettingValue(key, nextRaw);
            const cur = this.normalizeSettingValue(key, (this.project as any)[key]);

            const isSame = this.jsonEqual(next, cur);

            if (isSame) {
                delete (nextPending as Partial<Record<string, unknown>>)[key];
            } else {
                (nextPending as Partial<Record<string, unknown>>)[key] = nextRaw;
            }
        }

        this.pendingProjectUpdate = Object.keys(nextPending).length > 0 ? nextPending : null;

        this.recomputeUnsaved();
    }

    private updateProjectSettings(updateData: Partial<GetProjectRequest>) {
        this.projectsService.patchUpdateProject(this.project.id, updateData).subscribe({
            next: (updatedProject) => {
                this.project = updatedProject;
                this.projectStateService.setProject(updatedProject);

                // Update cache
                this.projectsService.updateProjectInCache(updatedProject);

                this.cdr.markForCheck();
                this.toastService.success('Project settings updated successfully');
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

                this.toastService.error(`Error updating project: ${errorMessage}`);
            },
        });
    }

    ngOnDestroy() {
        this.projectStateService.setProject(null);
        this.subscription.unsubscribe();
    }

    private normalizeDetails(input: { description: string; tags: string[] }) {
        const description = (input.description ?? '').trim();

        const tags = (input.tags ?? [])
            .map((t) => String(t ?? '').trim())
            .filter(Boolean)
            .map((t) => (t.startsWith('#') ? t.slice(1) : t))
            .map((t) => t.toLowerCase())
            .sort();

        return { description, tags };
    }

    public onDetailsChanged(change: { description: string; tags: string[] }): void {
        if (!this.project) return;

        const next = this.normalizeDetails(change);
        const current = this.normalizeDetails({
            description: this.project.description ?? '',
            tags: ((this.project as unknown as Record<string, unknown>)['tags'] as string[]) ?? [], // якщо tags є в моделі
        });

        const isSame =
            next.description === current.description && JSON.stringify(next.tags) === JSON.stringify(current.tags);

        if (isSame) {
            this.pendingProjectUpdate = null;
            this.hasUnsavedChanges = false;
            this.cdr.markForCheck();
            return;
        }

        this.pendingProjectUpdate = {
            description: change.description ?? '',
            tags: [...(change.tags ?? [])] as unknown as number[],
        };

        this.hasUnsavedChanges = true;
        this.cdr.markForCheck();
    }

    public onDetailsDirtyChange(isDirty: boolean): void {
        if (isDirty) {
            this.hasUnsavedChanges = true;
            this.cdr.markForCheck();
            return;
        }
        this.recomputeUnsaved();
    }

    public onSaveAll(): void {
        if (!this.project) return;

        if (this.tasksSection && !this.tasksSection.validateBeforeSave()) {
            this.toastService.warning('Please fill in all required fields.');
            return;
        }

        this.sanitizePendingTaskContexts();

        const appliedUpdate = this.pendingProjectUpdate;
        const agentUpdates = Array.from(this.pendingAgentUpdates.values());
        const taskUpdates = Array.from(this.pendingTaskUpdates.values());
        if (!appliedUpdate && agentUpdates.length === 0 && taskUpdates.length === 0) return;
        this.isSaving = true;
        this.cdr.markForCheck();

        const flushAgents$ =
            agentUpdates.length > 0
                ? forkJoin(agentUpdates.map((a) => this.agentsService.updateAgent(a as any)))
                : of([]);

        const deleteEvents = taskUpdates.filter((ev) => ev.kind === 'delete');
        const createEvents = taskUpdates.filter((ev) => ev.kind === 'create');
        const updateEvents = taskUpdates.filter((ev) => ev.kind === 'update');
        const deletedIds = new Set(
            deleteEvents
                .map((ev) => Number(asTaskPendingPayloadRecord(ev.payload)['id']))
                .filter((id) => Number.isFinite(id))
        );

        const delete$ =
            deleteEvents.length > 0
                ? forkJoin(
                      deleteEvents.map((ev) =>
                          this.tasksService.deleteTask(Number(asTaskPendingPayloadRecord(ev.payload)['id'])).pipe(
                              map((res) => ({ ev, res })),
                              catchError((error) => {
                                  if (error instanceof HttpErrorResponse && error.status === 404) {
                                      return of({ ev, res: null });
                                  }
                                  throw error;
                              })
                          )
                      )
                  )
                : of([]);

        const create$ =
            createEvents.length > 0
                ? forkJoin(
                      createEvents.map((ev) =>
                          this.tasksService
                              .createTask(this.sanitizeTaskPayloadByDeletedIds(ev.payload, deletedIds))
                              .pipe(map((res) => ({ ev, res })))
                      )
                  )
                : of([]);

        const update$ =
            updateEvents.length > 0
                ? forkJoin(
                      updateEvents.map((ev) =>
                          this.tasksService
                              .updateTask(this.sanitizeTaskPayloadByDeletedIds(ev.payload, deletedIds))
                              .pipe(map((res) => ({ ev, res })))
                      )
                  )
                : of([]);

        const shouldRunReorder = taskUpdates.some(
            (ev) => ev.kind === 'create' || ev.kind === 'delete' || ev.kind === 'reorder'
        );

        const flushTasks$ = delete$.pipe(
            switchMap(() => create$),
            tap((createResults: unknown[]) => {
                for (const item of createResults) {
                    const ev = (item as { ev?: TaskPendingEvent })?.ev;
                    const res = (item as { res?: { id?: number } })?.res;

                    if (ev?.kind === 'create' && res?.id != null) {
                        this.tasksSection?.applyCreatedTask(
                            ev.rowKey,
                            res as Parameters<TasksSectionComponent['applyCreatedTask']>[1]
                        );
                    }
                }
            }),
            switchMap(() => update$),
            tap((updateResults: unknown[]) => {
                for (const item of updateResults) {
                    const ev = (item as { ev?: TaskPendingEvent })?.ev;
                    const res = (item as { res?: Record<string, unknown> })?.res;

                    if (ev?.kind === 'update' && res != null) {
                        this.tasksSection?.applyUpdatedTask(
                            String(ev.rowKey),
                            res as Parameters<TasksSectionComponent['applyUpdatedTask']>[1]
                        );
                    }
                }
            }),
            switchMap(() => {
                if (!shouldRunReorder) {
                    return of([]);
                }

                const reorderPayload = (this.tasksSection?.getCurrentReorderPayload() ?? [])
                    .filter((x) => !deletedIds.has(Number(x.id)))
                    .sort((a, b) => a.order - b.order);

                if (reorderPayload.length === 0) {
                    return of([]);
                }

                return this.patchTaskOrderSequentially(reorderPayload);
            })
        );

        flushAgents$
            .pipe(
                tap(() => {
                    for (const a of agentUpdates) {
                        const id = Number((a as any).id);
                        if (Number.isFinite(id)) {
                            this.baselineAgentsById.set(id, structuredClone(a as any));
                        }
                    }
                    this.pendingAgentUpdates.clear();
                    this.recomputeUnsaved();
                }),
                switchMap(() => flushTasks$),
                tap((results: any[]) => {
                    for (const item of results) {
                        const ev = item?.ev;
                        const res = item?.res;

                        if (ev?.kind === 'create' && res?.id != null) {
                            this.tasksSection?.applyCreatedTask(ev.rowKey, res);
                        }
                    }

                    this.pendingTaskUpdates.clear();
                    this.tasksSection?.clearLocalDirtyAfterSave();
                    this.tasksLocalDirty = false;
                    this.recomputeUnsaved();
                }),
                switchMap(() => {
                    if (!appliedUpdate) return of(null);
                    return this.projectsService.patchUpdateProject(this.project!.id, appliedUpdate);
                }),
                finalize(() => {
                    this.isSaving = false;
                    this.cdr.markForCheck();
                })
            )
            .subscribe({
                next: (updatedProject: any) => {
                    if (appliedUpdate) {
                        const serverPatch = updatedProject ?? {};
                        this.project = { ...this.project!, ...appliedUpdate, ...serverPatch };
                        this.projectStateService.setProject(this.project);
                        this.projectsService.updateProjectInCache(this.project);
                        this.suppressNextSettingsEmit = true;
                        this.setupSections();
                        queueMicrotask(() => (this.suppressNextSettingsEmit = false));
                    }

                    this.pendingProjectUpdate = null;
                    this.recomputeUnsaved();
                    this.toastService.success('Project updated successfully');
                },
                error: (error: unknown) => {
                    const msg =
                        (error as any)?.error?.message ??
                        (appliedUpdate
                            ? 'Failed to update project'
                            : agentUpdates.length > 0 || taskUpdates.length > 0
                              ? 'Failed to save changes'
                              : 'Failed to save');
                    console.error(error);
                    this.toastService.error(msg);
                    this.cdr.markForCheck();
                },
            });
    }

    public get detailsTagsAsStrings(): string[] {
        const tags = (this.project as any)?.tags ?? [];
        return Array.isArray(tags) ? tags.map(String) : [];
    }

    private normalizeSettingValue(key: keyof GetProjectRequest, value: any): any {
        if (value === undefined) return undefined;
        return value;
    }

    private jsonEqual(a: unknown, b: unknown): boolean {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    public onAgentsIdsChanged(nextIds: number[]): void {
        if (!this.project) return;
        const next = this.normalizeAgentIds(nextIds);
        const cur = this.normalizeAgentIds((this.project as unknown as Record<string, unknown>)['agents'] as number[]);
        const isSame = JSON.stringify(next) === JSON.stringify(cur);
        const draft: Partial<GetProjectRequest> = { ...(this.pendingProjectUpdate ?? {}) };

        if (isSame) {
            delete (draft as Record<string, unknown>)['agents'];
        } else {
            draft.agents = nextIds;
        }

        this.pendingProjectUpdate = Object.keys(draft).length > 0 ? draft : null;

        this.recomputeUnsaved();
    }

    public onAgentUpdatePending(agent: FullAgent): void {
        const id = Number((agent as unknown as Record<string, unknown>)['id']);
        if (!Number.isFinite(id)) return;
        const baseline = this.baselineAgentsById.get(id);

        if (!baseline) {
            this.pendingAgentUpdates.set(id, agent);
            this.recomputeUnsaved();
            return;
        }

        const nextNorm = this.normalizeAgentForCompare(agent as unknown as Record<string, unknown>);
        const baseNorm = this.normalizeAgentForCompare(baseline as unknown as Record<string, unknown>);
        const isSame = this.jsonEqual(nextNorm, baseNorm);

        if (isSame) {
            this.pendingAgentUpdates.delete(id);
        } else {
            this.pendingAgentUpdates.set(id, agent);
        }

        this.recomputeUnsaved();
    }

    public onAgentsDirtyChange(): void {
        this.recomputeUnsaved();
    }

    public onTaskPending(ev: TaskPendingEvent): void {
        if (ev.payload == null) {
            this.pendingTaskUpdates.delete(ev.rowKey);
            this.recomputeUnsaved();
            this.cdr.markForCheck();
            return;
        }

        if (ev.kind === 'delete') {
            const deletedId = Number(asTaskPendingPayloadRecord(ev.payload)['id']);
            for (const [rowKey, pendingEv] of this.pendingTaskUpdates.entries()) {
                if (pendingEv.kind === 'create' || pendingEv.kind === 'update') {
                    const payloadRec = asTaskPendingPayloadRecord(pendingEv.payload);
                    const ctxList = payloadRec['task_context_list'];
                    if (Array.isArray(ctxList) && ctxList.some((id: unknown) => Number(id) === deletedId)) {
                        this.pendingTaskUpdates.set(rowKey, {
                            ...pendingEv,
                            payload: {
                                ...payloadRec,
                                task_context_list: ctxList.filter((id: unknown) => Number(id) !== deletedId),
                            },
                        });
                    }
                }
            }
        }

        this.pendingTaskUpdates.set(ev.rowKey, ev);
        this.recomputeUnsaved();
        this.cdr.markForCheck();
    }

    public onTasksDirtyChange(isDirty: boolean): void {
        this.tasksLocalDirty = isDirty;
        this.recomputeUnsaved();
    }

    public savePendingForLeave(): Observable<boolean> {
        if (!this.hasUnsavedChanges) return of(true);
        if (!this.project) return of(true);

        if (this.tasksSection && !this.tasksSection.validateBeforeSave()) {
            this.toastService.warning('Please fill in all required fields.');
            return of(false);
        }

        this.sanitizePendingTaskContexts();
        const appliedUpdate = this.pendingProjectUpdate;
        const agentUpdates = Array.from(this.pendingAgentUpdates.values());
        const taskUpdates = Array.from(this.pendingTaskUpdates.values()).filter((ev) => ev.payload != null);

        if (!appliedUpdate && agentUpdates.length === 0 && taskUpdates.length === 0) {
            return of(true);
        }

        this.isSaving = true;
        this.cdr.markForCheck();

        const flushAgents$ =
            agentUpdates.length > 0
                ? forkJoin(
                      agentUpdates.map((a) =>
                          this.agentsService.updateAgent(
                              a as unknown as import('../features/staff/models/agent.model').UpdateAgentRequest
                          )
                      )
                  )
                : of([]);

        const deleteEvents = taskUpdates.filter((ev) => ev.kind === 'delete');
        const createEvents = taskUpdates.filter((ev) => ev.kind === 'create');
        const updateEvents = taskUpdates.filter((ev) => ev.kind === 'update');
        const deletedIds = new Set(
            deleteEvents
                .map((ev) => Number(asTaskPendingPayloadRecord(ev.payload)['id']))
                .filter((id) => Number.isFinite(id))
        );

        const delete$ =
            deleteEvents.length > 0
                ? forkJoin(
                      deleteEvents.map((ev) =>
                          this.tasksService.deleteTask(Number(asTaskPendingPayloadRecord(ev.payload)['id'])).pipe(
                              map((res) => ({ ev, res })),
                              catchError((error) => {
                                  if (error instanceof HttpErrorResponse && error.status === 404) {
                                      return of({ ev, res: null });
                                  }
                                  throw error;
                              })
                          )
                      )
                  )
                : of([]);

        const create$ =
            createEvents.length > 0
                ? forkJoin(
                      createEvents.map((ev) =>
                          this.tasksService
                              .createTask(this.sanitizeTaskPayloadByDeletedIds(ev.payload, deletedIds))
                              .pipe(map((res) => ({ ev, res })))
                      )
                  )
                : of([]);

        const update$ =
            updateEvents.length > 0
                ? forkJoin(
                      updateEvents.map((ev) =>
                          this.tasksService
                              .updateTask(this.sanitizeTaskPayloadByDeletedIds(ev.payload, deletedIds))
                              .pipe(map((res) => ({ ev, res })))
                      )
                  )
                : of([]);

        const shouldRunReorder = taskUpdates.some(
            (ev) => ev.kind === 'create' || ev.kind === 'delete' || ev.kind === 'reorder'
        );

        const flushTasks$ = delete$.pipe(
            switchMap(() => create$),
            tap((createResults: unknown[]) => {
                for (const item of createResults) {
                    const ev = (item as { ev?: TaskPendingEvent; res?: { id?: number } })?.ev;
                    const res = (item as { ev?: TaskPendingEvent; res?: { id?: number } })?.res;

                    if (ev?.kind === 'create' && res?.id != null) {
                        this.tasksSection?.applyCreatedTask(
                            ev.rowKey,
                            res as Parameters<TasksSectionComponent['applyCreatedTask']>[1]
                        );
                    }
                }
            }),
            switchMap(() => update$),
            tap((updateResults: unknown[]) => {
                for (const item of updateResults) {
                    const ev = (item as { ev?: TaskPendingEvent; res?: Record<string, unknown> })?.ev;
                    const res = (item as { ev?: TaskPendingEvent; res?: Record<string, unknown> })?.res;

                    if (ev?.kind === 'update' && res != null) {
                        this.tasksSection?.applyUpdatedTask(
                            String(ev.rowKey),
                            res as Parameters<TasksSectionComponent['applyUpdatedTask']>[1]
                        );
                    }
                }
            }),
            switchMap(() => {
                if (!shouldRunReorder) {
                    return of([]);
                }

                const reorderPayload = (this.tasksSection?.getCurrentReorderPayload() ?? [])
                    .filter((x) => !deletedIds.has(Number(x.id)))
                    .sort((a, b) => a.order - b.order);

                if (reorderPayload.length === 0) {
                    return of([]);
                }

                return this.patchTaskOrderSequentially(reorderPayload);
            })
        );

        return flushAgents$.pipe(
            tap(() => this.pendingAgentUpdates.clear()),
            switchMap(() => flushTasks$),
            tap((results: unknown[]) => {
                for (const item of results) {
                    const ev = (item as { ev?: TaskPendingEvent; res?: { id?: number } })?.ev;
                    const res = (item as { ev?: TaskPendingEvent; res?: { id?: number } })?.res;
                    if (ev?.kind === 'create' && res?.id != null) {
                        this.tasksSection?.applyCreatedTask(
                            ev.rowKey,
                            res as Parameters<TasksSectionComponent['applyCreatedTask']>[1]
                        );
                    }
                }
                this.pendingTaskUpdates.clear();
                this.tasksSection?.clearLocalDirtyAfterSave();
                this.recomputeUnsaved();
                this.cdr.markForCheck();
            }),
            switchMap(() => {
                if (!appliedUpdate) return of(null);
                return this.projectsService.patchUpdateProject(this.project!.id, appliedUpdate);
            }),
            map((updatedProject: GetProjectRequest | null) => {
                if (appliedUpdate) {
                    const serverPatch = updatedProject ?? {};
                    this.project = { ...this.project!, ...appliedUpdate, ...serverPatch };
                    this.projectStateService.setProject(this.project);
                    this.projectsService.updateProjectInCache(this.project);
                    this.setupSections();
                }

                this.pendingProjectUpdate = null;
                this.hasUnsavedChanges = false;
                this.toastService.success('Project updated successfully');
                return true;
            }),
            catchError((error) => {
                console.error(error);
                const msg = (error as any)?.error?.message ?? 'Failed to save changes';
                this.toastService.error(msg);
                return of(false);
            }),
            finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            })
        );
    }

    public canDeactivate(): boolean | Observable<boolean> {
        if (!this.hasUnsavedChanges) return true;

        return this.unsavedChangesDialog
            .confirm({
                title: 'Unsaved Changes',
                message: 'You have unsaved changes on this page. What would you like to do?',
                saveText: 'Save & Leave',
                dontSaveText: "Don't Save & Leave",
                cancelText: 'Cancel',
                type: 'warning',
                onSave: () => this.savePendingForLeave(),
            })
            .pipe(
                tap((result) => {
                    if (result === 'dont-save') {
                        this.pendingProjectUpdate = null;
                        this.pendingAgentUpdates.clear();
                        this.pendingTaskUpdates.clear();
                        this.hasUnsavedChanges = false;
                        this.recomputeUnsaved();
                        this.cdr.markForCheck();
                    }
                }),
                map((result) => result === 'save' || result === 'dont-save')
            );
    }

    public discardPendingChanges(): void {
        this.pendingProjectUpdate = null;
        this.pendingAgentUpdates.clear();
        this.pendingTaskUpdates.clear();
        this.hasUnsavedChanges = false;

        this.recomputeUnsaved();
        this.cdr.markForCheck();
    }

    @HostListener('window:beforeunload', ['$event'])
    public onBeforeUnload(event: BeforeUnloadEvent): void {
        if (!this.hasUnsavedChanges) return;
        event.preventDefault();
        event.returnValue = '';
    }

    private sanitizePendingTaskContexts(): void {
        const deletedIds = new Set(
            Array.from(this.pendingTaskUpdates.values())
                .filter((ev) => ev.kind === 'delete')
                .map((ev) => Number(asTaskPendingPayloadRecord(ev.payload)['id']))
                .filter((id) => Number.isFinite(id))
        );

        for (const [rowKey, ev] of this.pendingTaskUpdates.entries()) {
            if (ev.kind !== 'create' && ev.kind !== 'update') {
                continue;
            }

            const payloadRec = asTaskPendingPayloadRecord(ev.payload);
            const ctxList = payloadRec['task_context_list'];
            if (!Array.isArray(ctxList)) {
                continue;
            }

            const sanitized = ctxList.filter((id: unknown) => !deletedIds.has(Number(id)));

            if (sanitized.length === ctxList.length) {
                continue;
            }

            this.pendingTaskUpdates.set(rowKey, {
                ...ev,
                payload: {
                    ...payloadRec,
                    task_context_list: sanitized,
                },
            });
        }
    }

    private sanitizeTaskPayloadByDeletedIds(payload: any, deletedIds: Set<number>): any {
        if (!payload) return payload;

        return {
            ...payload,
            task_context_list: Array.isArray(payload.task_context_list)
                ? payload.task_context_list.filter((id: unknown) => !deletedIds.has(Number(id)))
                : payload.task_context_list,
        };
    }

    private patchTaskOrderSequentially(reorderPayload: Array<{ id: number; order: number }>): Observable<any[]> {
        if (reorderPayload.length === 0) {
            return of([]);
        }

        const sorted = [...reorderPayload].sort((a, b) => a.order - b.order);

        return from(sorted).pipe(
            concatMap((item) =>
                this.tasksService.patchTaskOrder(item.id, item.order).pipe(map((res) => ({ item, res })))
            ),
            toArray()
        );
    }

    private tasksLocalDirty = false;
    private agentsLocalDirty = false;

    private recomputeUnsaved(): void {
        this.hasUnsavedChanges =
            this.pendingAgentUpdates.size > 0 ||
            this.pendingTaskUpdates.size > 0 ||
            !!this.pendingProjectUpdate ||
            this.agentsLocalDirty ||
            this.tasksLocalDirty;

        this.cdr.markForCheck();
    }

    private normalizeAgentIds(ids: number[] | null | undefined): number[] {
        return Array.from(new Set((ids ?? []).map((x) => Number(x))))
            .filter((x) => Number.isFinite(x))
            .sort((a, b) => a - b);
    }

    private normalizeAgentForCompare(agent: Record<string, unknown>): unknown {
        if (!agent) return agent;

        const a = structuredClone(agent) as Record<string, unknown>;
        const llmId = (a['fullFcmLlmConfig'] as Record<string, unknown> | null)?.['id'] ?? null;
        if (llmId != null && a['fcm_llm_config'] == null) {
            a['fcm_llm_config'] = llmId;
        }
        delete a['fullFcmLlmConfig'];
        delete a['selected_knowledge_source'];
        delete a['mergedTools'];

        if (a['fcm_llm_config'] != null) {
            a['fcm_llm_config'] = Number(a['fcm_llm_config']);
        }

        const walk = (v: unknown): unknown => {
            if (Array.isArray(v)) return v.map(walk);
            if (v && typeof v === 'object') {
                const out: any = {};
                for (const k of Object.keys(v).sort()) out[k] = walk((v as Record<string, unknown>)[k]);
                return out;
            }
            if (typeof v === 'number') return Number(v.toFixed(6));
            return v;
        };
        return walk(a);
    }
}
