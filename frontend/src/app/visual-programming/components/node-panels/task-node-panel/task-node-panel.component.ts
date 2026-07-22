import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
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
    TextareaComponent,
    TooltipComponent,
} from '@shared/components';
import { catchError, of } from 'rxjs';

import { AgentDefinition } from '../../../../features/agent-definitions/models/agent-definition.model';
import { Surface } from '../../../../features/agent-definitions/models/surface.model';
import { AgentDefinitionsApiService } from '../../../../features/agent-definitions/services/agent-definitions-api.service';
import { SurfacesApiService } from '../../../../features/agent-definitions/services/surfaces-api.service';
import { ToastService } from '../../../../services/notifications';
import { TaskNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { createInputMapFromPairs, getValidInputPairs, initializeInputMap } from '../node-panel-form.utils';

@Component({
    selector: 'app-task-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        TextareaComponent,
        InputMapComponent,
        JsonEditorComponent,
        SelectDropdownComponent,
        SelectDropdownTriggerDirective,
        MultiSelectComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
        TooltipComponent,
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
    public readonly outputSchemaExpanded = signal<boolean>(false);

    public readonly mainView = signal<'instructions' | 'schema'>('instructions');

    outputSchemaText = '{}';
    outputSchemaError = '';

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

    /**
     * "Local surface" (task-scoped) has no backend representation on the `Surface` model
     * yet (only `owner_agent: number | null` exists) — see plan Issues/doubts. Only the two
     * real groups populate for now; this recomputes whenever the selected agent changes.
     */
    public readonly surfaceMultiSelectItems = computed<SelectItem<number>[]>(() => {
        const agentId = this.agentDefinitionId();
        const items: SelectItem<number>[] = [];
        for (const surface of this.surfaces()) {
            if (surface.owner_agent === null) {
                items.push({ name: surface.name, value: surface.id, group: 'Shared Surfaces' });
            } else if (agentId != null && surface.owner_agent === agentId) {
                items.push({ name: surface.name, value: surface.id, group: 'Agent Surfaces' });
            }
        }
        return items;
    });

    public readonly surfaceSummaryLabel = computed<string>(() => {
        const total = this.selectedSurfaceIds().length;
        if (total === 0) return 'Assign surface';
        // Local (task-scoped) surfaces aren't backed by data yet — see surfaceMultiSelectItems.
        const localCount = 0;
        const assignedCount = total - localCount;
        return localCount > 0 ? `${assignedCount} assigned + ${localCount} local` : `${assignedCount} assigned`;
    });

    public readonly surfaceGroupIcons: Record<string, string> = {
        'Agent Surfaces': 'ti ti-robot',
        'Shared Surfaces': 'surfaces-tab',
    };

    constructor(
        private readonly sidePanelService: SidePanelService,
        private readonly agentDefinitionsApi: AgentDefinitionsApiService,
        private readonly surfacesApi: SurfacesApiService,
        private readonly toastService: ToastService
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
            .subscribe((surfaces) => this.surfaces.set(surfaces));
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
        this.pruneInvalidSurfaceSelection();
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onSurfacesChange(values: unknown[]): void {
        this.selectedSurfaceIds.set(values as number[]);
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    toggleOutputSchema(): void {
        this.outputSchemaExpanded.update((value) => !value);
    }

    toggleMainView(): void {
        this.mainView.update((value) => (value === 'instructions' ? 'schema' : 'instructions'));
    }

    expandPanel(): void {
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
        this.sidePanelService.triggerAutosave();
        this.notifyExternalChange();
    }

    onSchemaValidChange(isValid: boolean): void {
        this.outputSchemaError = isValid ? '' : 'Invalid JSON';
    }

    initializeForm(): FormGroup {
        const data = this.node().data;

        this.agentDefinitionId.set(data.agent_definition ?? null);
        this.selectedSurfaceIds.set(data.surface_list ?? []);
        this.outputSchemaExpanded.set(false);
        this.mainView.set('instructions');

        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            instructions: [data.instructions || '', Validators.required],
        });

        this.initializeInputMap(form);

        const schema = data.output_schema;
        this.outputSchemaText = schema && Object.keys(schema).length > 0 ? JSON.stringify(schema, null, 2) : '{}';

        return form;
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
                // `remember_output` has no control in the current Figma design — kept as-is.
                remember_output: this.node().data.remember_output ?? false,
                agent_definition: this.agentDefinitionId(),
                surface_list: this.selectedSurfaceIds(),
                // TODO: Local (inline) surface editor — see plan. Passed through unmodified
                // for now (no UI in this pass); defaults to `null` when absent.
                inline_surface: this.node().data.inline_surface ?? null,
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
            return JSON.parse(trimmed);
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

    private initializeInputMap(form: FormGroup): void {
        initializeInputMap(form, this.node().input_map as Record<string, unknown> | null | undefined, this.fb);
    }
}
