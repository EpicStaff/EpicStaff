import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    inject,
    Injector,
    input,
    signal,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    JsonEditorComponent,
    MultiSelectComponent,
    SelectDropdownComponent,
    SelectDropdownListItem,
    SelectDropdownTriggerDirective,
    SelectItem,
} from '@shared/components';
import { catchError, of } from 'rxjs';
import { v4 as uuidv4 } from 'uuid';

import { AgentDefinition } from '../../../../features/agent-definitions/models/agent-definition.model';
import { Surface } from '../../../../features/agent-definitions/models/surface.model';
import {
    SurfaceSummaryDialogComponent,
    SurfaceSummaryDialogData,
} from '../../../../features/agent-definitions/pages/agent-definitions-page/components/surface-summary-dialog/surface-summary-dialog.component';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { SurfacesApiService } from '../../../../features/agent-definitions/services/surfaces-api.service';
import { AgentNodeTaskUi } from '../../../../pages/flows-page/components/flow-visual-programming/models/agent-node.model';
import { InlineSurface } from '../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { ToastService } from '../../../../services/notifications';
import { ValidationErrorsComponent } from '../../../../shared/components/app-validation-errors/validation-errors.component';
import { OUTPUT_SCHEMA_EXAMPLE_HINT } from '../../../core/constants/output-schema-example-hint';
import { NodeType } from '../../../core/enums/node-type';
import { AgentNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NodeSurfaceCombineApiService } from '../../../services/node-surface-combine-api.service';
import { SidePanelService } from '../../../services/side-panel.service';
import {
    isValidOutputSchema,
    OUTPUT_SCHEMA_JSON_ERROR,
    OUTPUT_SCHEMA_RULE_ERROR,
} from '../../../utils/validation/output-schema.validator';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';
import { LocalSurfaceDialogService } from '../shared/local-surface-dialog/local-surface-dialog.service';
import { VariableHighlightTextareaComponent } from '../shared/variable-highlight-textarea/variable-highlight-textarea.component';
import { AgentTasksTableComponent } from './agent-tasks-table/agent-tasks-table.component';

type RightPaneSelection = { taskIndex: number; field: 'instructions' | 'schema' };

const LOCAL_SURFACE_VALUE = '__local_surface__';

@Component({
    selector: 'app-agent-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        MultiSelectComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
        JsonEditorComponent,
        AgentTasksTableComponent,
        ValidationErrorsComponent,
        VariableHighlightTextareaComponent,
    ],
    templateUrl: './agent-node-panel.component.html',
    styleUrls: ['./agent-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentNodePanelComponent extends BaseSidePanel<AgentNodeModel> {
    public readonly graphId = input<number | null>(null);

    public readonly agentDefinitions = signal<AgentDefinition[]>([]);
    public readonly surfaces = signal<Surface[]>([]);
    public readonly agentDefinitionId = signal<number | null>(null);
    public readonly selectedSurfaceIds = signal<number[]>([]);
    public readonly inlineSurface = signal<InlineSurface | null>(null);
    public readonly tasks = signal<AgentNodeTaskUi[]>([]);
    private readonly pendingAutoSelectAgentId = signal<number | null>(null);

    /** Both `<app-multi-select>` instances (compact + expanded views) for the surfaces
     *  dropdown — used to force-close whichever is open after the local-surface dialog
     *  resolves, so reopening re-seeds `tempSelected` from the up-to-date `selectedValues`. */
    private readonly surfaceMultiSelects = viewChildren(MultiSelectComponent);

    public readonly rightPane = signal<RightPaneSelection | null>(null);

    private readonly rightSchemaDrafts = signal<Record<string, string>>({});
    private readonly rightSchemaErrors = signal<Record<string, string>>({});
    public readonly outputSchemaExampleHint = OUTPUT_SCHEMA_EXAMPLE_HINT;

    public readonly agentItems = computed<SelectDropdownListItem<number>[]>(() =>
        this.agentDefinitions().map((agent) => ({ name: agent.name, value: agent.id }))
    );

    public readonly selectedAgentValue = computed<number[]>(() => {
        const id = this.agentDefinitionId();
        return id != null ? [id] : [];
    });

    public readonly selectedAgentName = computed<string | null>(() => {
        const id = this.agentDefinitionId();
        if (id == null) return null;
        return this.agentDefinitions().find((agent) => agent.id === id)?.name ?? null;
    });

    public readonly agentInvalid = computed<boolean>(() => {
        this.dirtyCheckTick();
        const control = this.form?.get('agent_definition');
        return !!control && control.invalid && control.touched;
    });

    public readonly tasksTouched = computed<boolean>(() => {
        this.dirtyCheckTick();
        return this.form?.get('tasksValidity')?.touched ?? false;
    });

    public readonly inputMapKeys = computed<string[]>(() => {
        this.dirtyCheckTick();
        if (!this.form) return [];
        return getValidInputPairs(this.inputMapPairs)
            .map((control) => ((control.value as { key?: string }).key ?? '').trim())
            .filter((key): key is string => key.length > 0);
    });

    /** Whether the node currently has a task-local (`inline_surface`) surface. There is at
     *  most one — its presence in the multi-select is represented by `LOCAL_SURFACE_VALUE`. */
    public readonly hasLocalSurface = computed<boolean>(() => this.inlineSurface() !== null);

    public readonly surfaceMultiSelectItems = computed<SelectItem<unknown>[]>(() => {
        const agentId = this.agentDefinitionId();
        const items: SelectItem<unknown>[] = [];

        if (this.hasLocalSurface()) {
            items.push({
                name: 'Local surface',
                value: LOCAL_SURFACE_VALUE,
                group: 'Local surface',
                trailingActionIcon: 'edit-label',
            });
        }

        for (const surface of this.surfaces()) {
            if (surface.owner_agent === null) {
                items.push({ name: surface.name, value: surface.id, group: 'Shared Surfaces' });
            } else if (agentId != null && surface.owner_agent === agentId) {
                items.push({ name: surface.name, value: surface.id, group: 'Agent Surfaces' });
            }
        }
        return items;
    });

    public readonly surfaceGroupActionIcon = computed<Record<string, string>>(() => {
        const icons: Record<string, string> = {};
        if (!this.hasLocalSurface()) {
            icons['Local surface'] = 'plus';
        }
        return icons;
    });

    public readonly surfaceSelectedValues = computed<unknown[]>(() =>
        this.hasLocalSurface() ? [...this.selectedSurfaceIds(), LOCAL_SURFACE_VALUE] : this.selectedSurfaceIds()
    );

    public readonly surfaceSummaryLabel = computed<string>(() => {
        const assigned = this.selectedSurfaceIds().length;
        const local = this.hasLocalSurface() ? 1 : 0;
        if (assigned === 0 && local === 0) return 'Assign surface';

        const parts: string[] = [];
        if (assigned > 0) parts.push(`${assigned} assigned`);
        if (local > 0) parts.push(`${local} local`);
        return parts.join(' + ');
    });

    public readonly surfaceGroupIcons: Record<string, string> = {
        'Local surface': 'local-surface',
        'Agent Surfaces': 'ti ti-robot',
        'Shared Surfaces': 'surfaces-tab',
    };

    public readonly effectiveRightPane = computed<RightPaneSelection | null>(() => {
        const taskList = this.tasks();
        if (taskList.length === 0) return null;
        const pane = this.rightPane();
        if (!pane || pane.taskIndex < 0 || pane.taskIndex >= taskList.length) {
            return { taskIndex: 0, field: 'instructions' };
        }
        return pane;
    });

    public readonly selectedTask = computed<AgentNodeTaskUi | null>(() => {
        const pane = this.effectiveRightPane();
        if (!pane) return null;
        return this.tasks()[pane.taskIndex] ?? null;
    });

    public readonly selectedTaskNumber = computed<number>(() => (this.effectiveRightPane()?.taskIndex ?? 0) + 1);

    private readonly dialog: Dialog = inject(Dialog);
    private readonly injector: Injector = inject(Injector);
    private readonly nodeSurfaceCombineApi: NodeSurfaceCombineApiService = inject(NodeSurfaceCombineApiService);

    constructor(
        private readonly sidePanelService: SidePanelService,
        private readonly agentDefinitionsApi: AgentDefinitionsApiService,
        private readonly surfacesApi: SurfacesApiService,
        private readonly toastService: ToastService,
        private readonly localSurfaceDialog: LocalSurfaceDialogService
    ) {
        super();
        this.agentDefinitionsApi
            .getAgentDefinitions()
            .pipe(
                catchError(() => of([])),
                takeUntilDestroyed()
            )
            .subscribe((defs) => this.agentDefinitions.set(defs));

        this.surfacesApi
            .getSurfaces()
            .pipe(
                catchError(() => of([])),
                takeUntilDestroyed()
            )
            .subscribe((surfaces) => {
                this.surfaces.set(surfaces);
                this.applyPendingAgentSurfaceAutoSelect();
            });

        this.sidePanelService.graphSaved$
            .pipe(takeUntilDestroyed())
            .subscribe(() => this.mergeReconciledTaskIdsAfterSave());
    }

    get activeColor(): string {
        return '#685fff';
    }

    get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    onAgentSelectionChange(values: unknown[]): void {
        const id = (values[0] as number | undefined) ?? null;
        this.agentDefinitionId.set(id);
        const agentControl = this.form.get('agent_definition');
        agentControl?.setValue(id);
        agentControl?.markAsTouched();
        agentControl?.markAsDirty();
        this.pruneInvalidSurfaceSelection();

        // Only while creating a brand-new (not yet persisted) node: pre-select every surface
        // the newly picked agent owns.
        const isNewNode = this.node().backendId == null;
        this.pendingAutoSelectAgentId.set(isNewNode && id != null ? id : null);
        if (isNewNode && id != null) {
            this.autoSelectAgentSurfaces(id);
        }

        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onSurfacesChange(values: unknown[]): void {
        const realIds = values.filter((v): v is number => v !== LOCAL_SURFACE_VALUE) as number[];
        this.selectedSurfaceIds.set(realIds);

        // Unchecking the local item removes it. Creation only happens via the "+" dialog.
        if (this.hasLocalSurface() && !values.includes(LOCAL_SURFACE_VALUE)) {
            this.inlineSurface.set(null);
        }

        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onCreateLocalSurface(): void {
        this.localSurfaceDialog
            .open({ mode: 'create', inlineSurface: null })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result) {
                    this.inlineSurface.set(result);
                    this.sidePanelService.triggerAutosave();
                    this.notifyExternalChange();
                }
                this.surfaceMultiSelects().forEach((ms) => ms.close());
            });
    }

    onEditLocalSurface(): void {
        this.localSurfaceDialog
            .open({ mode: 'edit', inlineSurface: this.inlineSurface() })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result) {
                    this.inlineSurface.set(result);
                    this.sidePanelService.triggerAutosave();
                    this.notifyExternalChange();
                }
                this.surfaceMultiSelects().forEach((ms) => ms.close());
            });
    }

    onTasksChange(tasks: AgentNodeTaskUi[]): void {
        this.tasks.set(tasks);
        this.clampRightPane(tasks);
        this.form.get('tasksValidity')?.updateValueAndValidity();
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onViewSummary(): void {
        const id = this.node().backendId;
        if (id == null) return;

        this.nodeSurfaceCombineApi
            .combineAgentNode(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (combined) => {
                    this.dialog.open<void, SurfaceSummaryDialogData>(SurfaceSummaryDialogComponent, {
                        width: 'calc(100vw - 2rem)',
                        height: 'calc(100vh - 2rem)',
                        maxWidth: '100vw',
                        panelClass: 'surface-summary-dialog-panel',
                        injector: this.injector,
                        data: {
                            combined,
                            placeLabel: this.node().data.name || 'Surface Summary',
                            hideInstructions: true,
                            hideDescriptions: true,
                        },
                    });
                },
                error: () => {
                    // Backend endpoint may not exist yet — fail quietly.
                },
            });
    }

    onCellSelect(selection: RightPaneSelection): void {
        if (!this.isExpanded()) {
            this.sidePanelService.requestExpand();
        }
        this.resyncRightSchemaDraft(selection);
        this.rightPane.set(selection);
    }

    toggleRightPaneField(): void {
        const pane = this.effectiveRightPane();
        if (!pane) return;
        const next: RightPaneSelection = {
            taskIndex: pane.taskIndex,
            field: pane.field === 'instructions' ? 'schema' : 'instructions',
        };
        this.resyncRightSchemaDraft(next);
        this.rightPane.set(next);
    }

    rightInstructionsValue(): string {
        return this.selectedTask()?.instructions ?? '';
    }

    onRightInstructionsInput(value: string): void {
        const task = this.selectedTask();
        if (!task) return;
        this.updateSelectedTaskField(task.tempId, { instructions: value });
    }

    copyRightInstructions(): void {
        this.copyToClipboard(this.selectedTask()?.instructions ?? '');
    }

    rightSchemaText(): string {
        const task = this.selectedTask();
        if (!task) return '{}';
        const draft = this.rightSchemaDrafts()[task.tempId];
        return draft !== undefined ? draft : this.stringifySchema(task.output_schema);
    }

    rightSchemaError(): string {
        const task = this.selectedTask();
        if (!task) return '';
        return this.rightSchemaErrors()[task.tempId] ?? '';
    }

    onRightSchemaChange(json: string): void {
        const task = this.selectedTask();
        if (!task) return;

        this.rightSchemaDrafts.update((drafts) => ({ ...drafts, [task.tempId]: json }));

        const trimmed = json.trim();
        try {
            const parsed = trimmed === '' ? {} : JSON.parse(trimmed);
            this.updateSelectedTaskField(task.tempId, { output_schema: parsed, output_schema_invalid: false });
            this.setRightSchemaError(task.tempId, isValidOutputSchema(parsed) ? '' : OUTPUT_SCHEMA_RULE_ERROR);
        } catch {
            this.updateSelectedTaskField(task.tempId, { output_schema_invalid: true });
            this.setRightSchemaError(task.tempId, OUTPUT_SCHEMA_JSON_ERROR);
        }
    }

    private resyncRightSchemaDraft(selection: RightPaneSelection): void {
        const current = this.rightPane();
        if (current && current.taskIndex === selection.taskIndex && current.field === selection.field) {
            return;
        }
        const task = this.tasks()[selection.taskIndex];
        if (!task || task.output_schema_invalid) return;
        this.rightSchemaDrafts.update((drafts) => {
            if (!(task.tempId in drafts)) return drafts;
            return Object.fromEntries(Object.entries(drafts).filter(([key]) => key !== task.tempId));
        });
    }

    private setRightSchemaError(tempId: string, message: string): void {
        this.rightSchemaErrors.update((errors) => {
            if (!message) {
                if (!(tempId in errors)) return errors;
                return Object.fromEntries(Object.entries(errors).filter(([key]) => key !== tempId));
            }
            return { ...errors, [tempId]: message };
        });
    }

    addTask(): void {
        const newTask: AgentNodeTaskUi = {
            tempId: uuidv4(),
            name: '',
            instructions: '',
            output_schema: {},
            output_schema_invalid: false,
            contextRefs: [],
        };
        this.onTasksChange([...this.tasks(), newTask]);
    }

    getTasksErrorMessage(): string {
        const errors: ValidationErrors | null | undefined = this.form?.get('tasksValidity')?.errors;
        if (!errors) return '';
        if (errors['tasksRequired']) return 'Add at least one task.';
        if (errors['taskNameRequired']) return 'Every task needs a name.';
        if (errors['taskNameDuplicate']) return 'Task names must be unique.';
        if (errors['taskInstructionsRequired']) return 'Every task needs instructions.';
        return '';
    }

    initializeForm(): FormGroup {
        const data = this.node().data;

        this.agentDefinitionId.set(data.agent_definition ?? null);
        this.selectedSurfaceIds.set(data.surface_list ?? []);
        this.inlineSurface.set(data.inline_surface ?? null);
        this.tasks.set(this.cloneTasks(data.tasks ?? []));
        this.rightPane.set(null);
        this.rightSchemaDrafts.set({});
        this.rightSchemaErrors.set({});

        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            agent_definition: [data.agent_definition ?? null, Validators.required],
            tasksValidity: [true, this.tasksValidator()],
        });

        this.initializeInputMap(form);

        return form;
    }

    createUpdatedNode(): AgentNodeModel {
        const validInputPairs = getValidInputPairs(this.inputMapPairs);
        const inputMapValue = createInputMapFromPairs(validInputPairs);

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...this.node().data,
                name: this.form.value.node_name || 'Agent Node',
                agent_definition: this.agentDefinitionId(),
                surface_list: this.selectedSurfaceIds(),
                inline_surface: this.inlineSurface(),
                tasks: this.tasks(),
            },
        };
    }

    private tasksValidator(): ValidatorFn {
        return (): ValidationErrors | null => {
            const tasks = this.tasks();
            if (!tasks || tasks.length === 0) {
                return { tasksRequired: true };
            }
            const trimmedNames = tasks.map((t) => (t.name ?? '').trim());
            if (trimmedNames.some((n) => n === '')) {
                return { taskNameRequired: true };
            }
            const seen = new Set<string>();
            for (const n of trimmedNames) {
                if (seen.has(n)) return { taskNameDuplicate: true };
                seen.add(n);
            }
            if (tasks.some((t) => !(t.instructions ?? '').trim())) {
                return { taskInstructionsRequired: true };
            }
            return null;
        };
    }

    private updateSelectedTaskField(tempId: string, patch: Partial<AgentNodeTaskUi>): void {
        this.tasks.update((tasks) => tasks.map((t) => (t.tempId === tempId ? { ...t, ...patch } : t)));
        this.form.get('tasksValidity')?.updateValueAndValidity();
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    private stringifySchema(schema: Record<string, unknown> | null | undefined): string {
        if (!schema || Object.keys(schema).length === 0) return '{}';
        try {
            return JSON.stringify(schema, null, 2);
        } catch {
            return '{}';
        }
    }

    private copyToClipboard(text: string): void {
        navigator.clipboard
            .writeText(text)
            .then(() => this.toastService.success('Copied to clipboard!', 3000, 'bottom-right'))
            .catch(() => this.toastService.error('Failed to copy', 3000, 'top-right'));
    }

    private clampRightPane(tasks: AgentNodeTaskUi[]): void {
        const pane = this.rightPane();
        if (!pane) return;
        if (tasks.length === 0) {
            this.rightPane.set(null);
        } else if (pane.taskIndex >= tasks.length) {
            const next: RightPaneSelection = { taskIndex: 0, field: 'instructions' };
            this.resyncRightSchemaDraft(next);
            this.rightPane.set(next);
        }
    }

    /**
     * After a full graph save, `patchFlowStateWithBackendIds` reconciles freshly created
     * tasks' backend `id`s (and any sibling `contextRefs` that referenced them by `tempId`)
     * into the flow-state node model. That patched node reaches this panel via the SAME
     * `node()` input signal (new object reference, same node id) — but `shouldReinitializeForm`
     * only re-runs `initializeForm()` on a node-ID change, so the panel's own `tasks` signal
     * would otherwise keep holding the id-less copies forever. On the NEXT save those rows
     * would be sent as `temp_id`-only again, causing the backend to delete + recreate the
     * same tasks.
     *
     * IMPORTANT (timing): `graphSaved$` is a plain RxJS Subject fired synchronously right
     * after `flowService.setFlow(patchedFlow)` (see flow-visual-programming.component.ts's
     * `saveFlowState`/`saveNodeToBackend`). This handler therefore runs in the SAME
     * synchronous call stack. `this.node()` is a component INPUT bound through
     * `NgComponentOutlet`'s `ngComponentOutletInputs` (node-panel-shell.component.ts) — inputs
     * only receive their new value on Angular's NEXT change-detection pass, so reading
     * `this.node()` here would still yield the PRE-patch node. `SidePanelService.selectedNode`
     * is a `computed()` over `flowService.nodes()`, which recomputes the instant it's read —
     * it reflects the patched state synchronously. Read the patched node from there instead.
     *
     * Matches local rows to the incoming (patched) node's rows by `tempId` and adopts only
     * the reconciled `id` (and any resolved sibling `contextRefs`) — never overwrites
     * name/instructions/schema or any other in-progress user edit. Re-baselines the dirty
     * snapshot afterwards so this silent reconciliation never flashes the Save button.
     */
    private mergeReconciledTaskIdsAfterSave(): void {
        const currentNode = this.sidePanelService.selectedNode();
        if (!currentNode || currentNode.id !== this.node().id || currentNode.type !== NodeType.AGENT) return;

        const incomingTasks = currentNode.data.tasks ?? [];
        if (incomingTasks.length === 0) return;

        const incomingByTempId = new Map<string, AgentNodeTaskUi>();
        for (const t of incomingTasks) {
            if (t.tempId) incomingByTempId.set(t.tempId, t);
        }
        if (incomingByTempId.size === 0) return;

        let changed = false;
        const merged = this.tasks().map((task) => {
            const incoming = incomingByTempId.get(task.tempId);
            if (!incoming) return task;

            let next = task;

            if (next.id == null && incoming.id != null) {
                next = { ...next, id: incoming.id };
                changed = true;
            }

            if (next.contextRefs?.length && incoming.contextRefs?.length) {
                const resolvedIdByTempId = new Map<string, number>();
                for (const ref of incoming.contextRefs) {
                    if (ref.tempId && ref.id != null) resolvedIdByTempId.set(ref.tempId, ref.id);
                }
                if (resolvedIdByTempId.size > 0) {
                    let refsChanged = false;
                    const nextRefs = next.contextRefs.map((ref) => {
                        if (ref.id == null && ref.tempId != null) {
                            const resolvedId = resolvedIdByTempId.get(ref.tempId);
                            if (resolvedId != null) {
                                refsChanged = true;
                                return { id: resolvedId };
                            }
                        }
                        return ref;
                    });
                    if (refsChanged) {
                        next = { ...next, contextRefs: nextRefs };
                        changed = true;
                    }
                }
            }

            return next;
        });

        if (!changed) return;

        this.tasks.set(merged);
        this.onSaveSilently();
    }

    private cloneTasks(tasks: AgentNodeTaskUi[]): AgentNodeTaskUi[] {
        return tasks.map((t) => ({
            ...t,
            output_schema: t.output_schema ? { ...t.output_schema } : {},
            contextRefs: t.contextRefs ? t.contextRefs.map((r) => ({ ...r })) : [],
        }));
    }

    private pruneInvalidSurfaceSelection(): void {
        const validIds = new Set(this.surfaceMultiSelectItems().map((item) => item.value));
        const next = this.selectedSurfaceIds().filter((id) => validIds.has(id));
        if (next.length !== this.selectedSurfaceIds().length) {
            this.selectedSurfaceIds.set(next);
        }
    }

    private autoSelectAgentSurfaces(agentId: number): void {
        const validSurfaceIds = new Set(this.surfaces().map((surface) => surface.id));

        const ownedSurfaceIds = this.surfaces()
            .filter((surface) => surface.owner_agent === agentId)
            .map((surface) => surface.id);

        const assignedSharedSurfaceIds = (
            this.agentDefinitions().find((agent) => agent.id === agentId)?.default_surfaces ?? []
        )
            .map((defaultSurface) => defaultSurface.surface)
            .filter((surfaceId) => validSurfaceIds.has(surfaceId));

        const agentSurfaceIds = [...ownedSurfaceIds, ...assignedSharedSurfaceIds];
        if (agentSurfaceIds.length === 0) return;
        this.selectedSurfaceIds.update((current) => Array.from(new Set([...current, ...agentSurfaceIds])));
    }

    private applyPendingAgentSurfaceAutoSelect(): void {
        const pendingAgentId = this.pendingAutoSelectAgentId();
        if (pendingAgentId == null) return;
        this.pendingAutoSelectAgentId.set(null);
        if (this.node().backendId != null || this.agentDefinitionId() !== pendingAgentId) return;
        this.autoSelectAgentSurfaces(pendingAgentId);
    }

    private initializeInputMap(form: FormGroup): void {
        initializeInputMap(form, this.node().input_map as Record<string, unknown> | null | undefined, this.fb);
    }
}
