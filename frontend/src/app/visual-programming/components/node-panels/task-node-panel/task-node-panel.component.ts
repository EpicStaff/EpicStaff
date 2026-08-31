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
import { FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
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
    TooltipComponent,
} from '@shared/components';
import { MarkdownComponent } from 'ngx-markdown';
import { catchError, of } from 'rxjs';

import {
    AgentDefinition,
    FLOW_CONTEXT_PLACES,
} from '../../../../features/agent-definitions/models/agent-definition.model';
import { Surface } from '../../../../features/agent-definitions/models/surface.model';
import {
    SurfaceSummaryDialogComponent,
    SurfaceSummaryDialogData,
} from '../../../../features/agent-definitions/pages/agent-definitions-page/components/surface-summary-dialog/surface-summary-dialog.component';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { SurfacesApiService } from '../../../../features/agent-definitions/services/surfaces-api.service';
import { InlineSurface } from '../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { ToastService } from '../../../../services/notifications';
import { ValidationErrorsComponent } from '../../../../shared/components/app-validation-errors/validation-errors.component';
import { ToggleSwitchComponent } from '../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { OUTPUT_SCHEMA_EXAMPLE_HINT } from '../../../core/constants/output-schema-example-hint';
import { TaskNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NodeSurfaceCombineApiService } from '../../../services/node-surface-combine-api.service';
import { SidePanelService } from '../../../services/side-panel.service';
import {
    isValidOutputSchema,
    OUTPUT_SCHEMA_JSON_ERROR,
    OUTPUT_SCHEMA_RULE_ERROR,
} from '../../../utils/validation/output-schema.validator';
import { InputMapComponent } from '../../input-map/input-map.component';
import { LockableFieldComponent } from '../../lockable-field/lockable-field.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';
import {
    InstructionsView,
    InstructionsViewToggleComponent,
} from '../shared/instructions-view-toggle/instructions-view-toggle.component';
import { LocalSurfaceDialogService } from '../shared/local-surface-dialog/local-surface-dialog.service';
import { VariableHighlightTextareaComponent } from '../shared/variable-highlight-textarea/variable-highlight-textarea.component';

const LOCAL_SURFACE_VALUE = '__local_surface__';

@Component({
    selector: 'app-task-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        VariableHighlightTextareaComponent,
        InputMapComponent,
        JsonEditorComponent,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        MultiSelectComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
        TooltipComponent,
        ValidationErrorsComponent,
        ToggleSwitchComponent,
        InstructionsViewToggleComponent,
        MarkdownComponent,
        LockableFieldComponent,
    ],
    templateUrl: './task-node-panel.component.html',
    styleUrls: ['./task-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TaskNodePanelComponent extends BaseSidePanel<TaskNodeModel> {
    public readonly graphId = input<number | null>(null);

    public readonly agentDefinitions = signal<AgentDefinition[]>([]);
    public readonly surfaces = signal<Surface[]>([]);
    public readonly agentDefinitionId = signal<number | null>(null);
    public readonly selectedSurfaceIds = signal<number[]>([]);
    public readonly inlineSurface = signal<InlineSurface | null>(null);
    public readonly outputSchemaExpanded = signal<boolean>(false);
    private readonly pendingAutoSelectAgentId = signal<number | null>(null);

    public readonly mainView = signal<'instructions' | 'schema'>('instructions');
    public readonly instructionsView = signal<InstructionsView>('preview');
    public readonly outputSchemaExampleHint = OUTPUT_SCHEMA_EXAMPLE_HINT;
    private readonly surfaceMultiSelects = viewChildren(MultiSelectComponent);

    outputSchemaText = '{}';
    outputSchemaError = '';
    private outputSchemaDraftInvalid = false;

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

    public readonly instructionsInvalid = computed<boolean>(() => {
        this.dirtyCheckTick();
        const control = this.form?.get('instructions');
        return !!control && control.invalid && control.touched;
    });

    public readonly instructionsValue = computed<string>(() => {
        this.dirtyCheckTick();
        return (this.form?.get('instructions')?.value as string) ?? '';
    });

    public readonly inputMapKeys = computed<string[]>(() => {
        this.dirtyCheckTick();
        if (!this.form) return [];
        return getValidInputPairs(this.inputMapPairs)
            .map((control) => ((control.value as { key?: string }).key ?? '').trim())
            .filter((key): key is string => key.length > 0);
    });

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

    onViewSummary(): void {
        const id = this.node().backendId;
        if (id == null) return;

        this.nodeSurfaceCombineApi
            .combineTaskNode(id)
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

    toggleOutputSchema(): void {
        this.outputSchemaExpanded.update((value) => !value);
    }

    toggleMainView(): void {
        this.mainView.update((value) => (value === 'instructions' ? 'schema' : 'instructions'));
    }

    setInstructionsView(view: InstructionsView): void {
        this.instructionsView.set(view);
    }

    expandPanel(): void {
        this.mainView.set('schema');
        this.sidePanelService.requestExpand();
    }

    copyInstructions(): void {
        this.copyToClipboard(this.form.get('instructions')?.value || '');
    }

    copySchema(): void {
        this.copyToClipboard(this.outputSchemaText);
    }

    private copyToClipboard(text: string): void {
        navigator.clipboard
            .writeText(text)
            .then(() => this.toastService.success('Copied to clipboard!', 3000, 'bottom-right'))
            .catch(() => this.toastService.error('Failed to copy', 3000, 'top-right'));
    }

    onSchemaEditorChange(json: string): void {
        this.outputSchemaText = json;
        this.recomputeOutputSchemaValidity(json);
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onSchemaValidChange(isValid: boolean): void {
        if (isValid) {
            this.recomputeOutputSchemaValidity(this.outputSchemaText);
            return;
        }
        this.outputSchemaDraftInvalid = true;
        this.outputSchemaError = OUTPUT_SCHEMA_JSON_ERROR;
    }

    /** Combined JSON-syntax + Output Schema rule (1–3) check on the current draft text. */
    private recomputeOutputSchemaValidity(json: string): void {
        const trimmed = json.trim();
        if (!trimmed) {
            this.outputSchemaDraftInvalid = false;
            this.outputSchemaError = '';
            return;
        }
        try {
            const parsed = JSON.parse(trimmed);
            const rulesOk = isValidOutputSchema(parsed);
            this.outputSchemaDraftInvalid = !rulesOk;
            this.outputSchemaError = rulesOk ? '' : OUTPUT_SCHEMA_RULE_ERROR;
        } catch {
            this.outputSchemaDraftInvalid = true;
            this.outputSchemaError = OUTPUT_SCHEMA_JSON_ERROR;
        }
    }

    initializeForm(): FormGroup {
        const data = this.node().data;

        this.agentDefinitionId.set(data.agent_definition ?? null);
        this.selectedSurfaceIds.set(data.surface_list ?? []);
        this.inlineSurface.set(data.inline_surface ?? null);

        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            remember_output: [data.remember_output ?? false],
            instructions: [data.instructions || '', Validators.required],
            agent_definition: [data.agent_definition ?? null, Validators.required],
        });

        this.initializeInputMap(form);

        return form;
    }

    protected override onFormReinitialized(): void {
        const data = this.node().data;
        this.outputSchemaExpanded.set(false);
        this.mainView.set('instructions');
        this.instructionsView.set((data.instructions || '').trim() ? 'preview' : 'edit');
        this.outputSchemaText = this.schemaToText(data.output_schema);
        this.outputSchemaDraftInvalid = false;
        this.outputSchemaError = '';
    }

    protected override onRemoteFormMerged(): void {
        if (this.outputSchemaDraftInvalid) return;
        const remote = this.node().data.output_schema ?? {};
        if (JSON.stringify(this.parsedOutputSchema()) === JSON.stringify(remote)) return;
        this.outputSchemaText = this.schemaToText(remote);
        this.outputSchemaError = '';
    }

    private schemaToText(schema: Record<string, unknown> | undefined): string {
        return schema && Object.keys(schema).length > 0 ? JSON.stringify(schema, null, 2) : '{}';
    }

    createUpdatedNode(): TaskNodeModel {
        const validInputPairs = getValidInputPairs(this.inputMapPairs);
        const inputMapValue = createInputMapFromPairs(validInputPairs);

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...this.node().data,
                name: this.form.value.node_name || 'Task Node',
                instructions: this.form.value.instructions || '',
                output_schema: this.parsedOutputSchema(),
                output_schema_invalid: this.outputSchemaDraftInvalid,
                remember_output: this.form.value.remember_output ?? false,
                agent_definition: this.agentDefinitionId(),
                surface_list: this.selectedSurfaceIds(),
                inline_surface: this.inlineSurface(),
            },
        };
    }

    /**
     * `output_schema` is a non-nullable JSONField on the backend — always resolve to a JSON
     * object, never `null`/a string. Empty/blank editor text resolves to `{}` ("no schema").
     */
    private parsedOutputSchema(): Record<string, unknown> {
        const trimmed = this.outputSchemaText.trim();
        if (!trimmed) return {};
        try {
            const parsed = JSON.parse(trimmed);
            if (!isValidOutputSchema(parsed)) return this.node().data.output_schema ?? {};
            return parsed;
        } catch {
            return this.node().data.output_schema ?? {};
        }
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
        const flowContextSurfaceIds = (
            this.agentDefinitions().find((agent) => agent.id === agentId)?.default_surfaces ?? []
        )
            .filter((defaultSurface) => FLOW_CONTEXT_PLACES.includes(defaultSurface.place))
            .map((defaultSurface) => defaultSurface.surface)
            .filter((surfaceId) => validSurfaceIds.has(surfaceId));

        if (flowContextSurfaceIds.length === 0) return;
        this.selectedSurfaceIds.update((current) => Array.from(new Set([...current, ...flowContextSurfaceIds])));
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
