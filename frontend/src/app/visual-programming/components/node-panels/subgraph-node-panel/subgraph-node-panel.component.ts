import { ChangeDetectionStrategy, Component, computed, inject, input, OnInit, signal } from '@angular/core';
import { FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    CustomInputComponent,
    GoToButtonComponent,
    HelpTooltipComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';

import { GetGraphLightRequest } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
// import { flowUrl } from '@shared/utils';
import { SubGraphNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NODE_PANEL_DIFF } from '../../../core/providers/node-panel-diff.token';
import { linkedEntityFormat, mapFieldRowChanges } from '../../../utils/diff';
import { DiffFieldMarkComponent } from '../../diff-field-mark/diff-field-mark.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { inputMapFromRows } from '../../input-map/input-map-rows';
import { MissingReferenceNoteComponent } from '../../missing-reference-note/missing-reference-note.component';

const MISSING_FLOW_MESSAGE = "This node's flow was deleted.";

@Component({
    selector: 'app-subgraph-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        GoToButtonComponent,
        HelpTooltipComponent,
        SelectComponent,
        ValidationErrorsComponent,
        MissingReferenceNoteComponent,
        DiffFieldMarkComponent,
    ],
    templateUrl: './subgraph-node-panel.component.html',
    styleUrls: ['./subgraph-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SubGraphNodePanelComponent extends BaseSidePanel<SubGraphNodeModel> implements OnInit {
    private flowsApiService = inject(FlowsApiService);

    public availableFlows = signal<GetGraphLightRequest[]>([]);
    public readonly currentFlowId = input<number | null>(null);
    public readonly filteredFlows = computed(() => {
        const currentId = this.currentFlowId();
        if (!currentId) {
            return this.availableFlows();
        }
        return this.availableFlows().filter((flow) => flow.id !== currentId);
    });

    public readonly flowItems = computed<SelectItem[]>(() =>
        this.filteredFlows().map((flow) => ({ name: flow.name, value: flow.id }))
    );
    /** Changes tab of a version preview: what a restore does to each Input List row; `null` anywhere else. */
    protected readonly inputMapRowChanges = computed(() => mapFieldRowChanges(this.panelDiff(), 'input_map'));
    /** The flows listed for the select name the subflow in the mark's tooltip; one not listed shows as `flow #id`. */
    protected readonly flowNameFormat = linkedEntityFormat(
        'flow',
        (id) => this.availableFlows().find((flow) => flow.id === id)?.name
    );

    private readonly panelDiff = inject(NODE_PANEL_DIFF);

    /**
     * The chosen flow is one the user can open. `form` is not a signal: `dirtyCheckTick` follows its edits,
     * and `node()` the new form the base effect builds when this panel instance is given another node.
     */
    public readonly selectedFlowExists = computed(() => {
        this.node();
        this.dirtyCheckTick();
        const id = Number(this.form?.get('selectedFlowId')?.value);
        if (!id) return false;
        return this.availableFlows().some((flow) => flow.id === id);
    });

    /** Shown while the node's flow is deleted and no other flow is chosen yet. */
    protected readonly missingFlowHint = computed(() => {
        if (!this.node().isBlocked || this.selectedFlowExists()) return null;
        return this.isReadOnly() ? MISSING_FLOW_MESSAGE : `${MISSING_FLOW_MESSAGE} Select another flow.`;
    });

    constructor() {
        super();
    }

    public get activeColor(): string {
        return 'var(--accent-color)';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    ngOnInit(): void {
        this.flowsApiService.getGraphsLight().subscribe({
            next: (flows: GetGraphLightRequest[]) => {
                this.availableFlows.set(flows);
            },
            error: (err) => console.error('Error fetching flows:', err),
        });
    }

    protected initializeForm(): FormGroup {
        const currentFlowId = this.currentFlowId();
        // A blocked node's flow is gone (its id is null, or not a flow the user has), so the user picks a new one.
        const selectedId = this.node().isBlocked ? null : (this.node().data.id ?? null);
        const initialSelectedId = currentFlowId && selectedId === currentFlowId ? null : selectedId;

        const form = this.fb.group({
            node_name: [this.node().node_name || '', this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            selectedFlowId: [initialSelectedId, Validators.required],
        });

        this.initializeInputMap(form);
        return form;
    }

    public onFlowChange(): void {}

    protected createUpdatedNode(): SubGraphNodeModel {
        const selectedId = Number(this.form.get('selectedFlowId')?.value);
        const originalId = this.node().data.id;

        let updatedData = this.node().data;
        let isBlocked = this.node().isBlocked;
        if (selectedId !== originalId || isBlocked) {
            const selectedFlow = this.availableFlows().find((f) => f.id === selectedId);
            if (selectedFlow) {
                updatedData = {
                    id: selectedFlow.id,
                    uuid: selectedFlow.uuid,
                    name: selectedFlow.name,
                    description: selectedFlow.description,
                    tags: selectedFlow.tags || [],
                };
                isBlocked = false;
            }
        }

        const inputMapValue = inputMapFromRows(this.inputMapPairs.getRawValue());

        return {
            ...this.node(),
            node_name: this.form.get('node_name')?.value || this.node().node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: updatedData,
            isBlocked,
        };
    }

    private initializeInputMap(form: FormGroup): void {
        const inputMapArray = form.get('input_map') as FormArray;

        if (this.node().input_map && Object.keys(this.node().input_map).length > 0) {
            Object.entries(this.node().input_map).forEach(([key, value]) => {
                inputMapArray.push(
                    this.fb.group({
                        key: [key, Validators.required],
                        value: [value, Validators.required],
                    })
                );
            });
        } else {
            inputMapArray.push(
                this.fb.group({
                    key: [''],
                    value: ['variables.'],
                })
            );
        }
    }

    public getSelectedFlowUrl(): string | null {
        const id = this.form.get('selectedFlowId')?.value;
        if (!id) return null;
        return `/flows/${Number(id)}`;
    }
}
