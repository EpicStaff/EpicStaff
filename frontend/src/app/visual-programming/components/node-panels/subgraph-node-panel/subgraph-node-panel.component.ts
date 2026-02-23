import { ChangeDetectionStrategy, Component, signal, inject, OnInit, input, computed } from '@angular/core';
import { ReactiveFormsModule, FormGroup, Validators, FormArray } from '@angular/forms';
import { SubGraphNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CommonModule } from '@angular/common';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { GraphDto } from '../../../../features/flows/models/graph.model';
import { InputMapComponent } from '../../input-map/input-map.component';

interface InputMapPair {
    key: string;
    value: string;
}

@Component({
    standalone: true,
    selector: 'app-subgraph-node-panel',
    imports: [ReactiveFormsModule, CommonModule, CustomInputComponent, InputMapComponent],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">
                    <app-custom-input
                        label="Node Name"
                        tooltipText="The unique identifier used to reference this subgraph node. This name must be unique within the flow."
                        formControlName="node_name"
                        placeholder="Enter node name"
                        [activeColor]="activeColor"
                        [errorMessage]="getNodeNameErrorMessage()"
                    ></app-custom-input>

                    <div class="input-map">
                        <app-input-map
                            [activeColor]="activeColor"
                        ></app-input-map>
                    </div>

                    <app-custom-input
                        label="Output Variable Path"
                        tooltipText="The path where the output of this node will be stored in your flow variables. Leave empty if you don't need to store the output."
                        formControlName="output_variable_path"
                        placeholder="Enter output variable path (leave empty for null)"
                        [activeColor]="activeColor"
                    ></app-custom-input>

                    <div class="field">
                        <label>
                            Selected Flow
                            <i class="ti ti-help-circle tooltip-icon" title="Select the flow that this node will execute"></i>
                        </label>
                        <select
                            formControlName="selectedFlowId"
                            class="select-field"
                            (change)="onFlowChange()"
                        >
                            <option [value]="null" disabled>Select a flow</option>
                            @for (flow of filteredFlows(); track flow.id) {
                            <option [value]="flow.id">{{ flow.name }}</option>
                            }
                        </select>
                    </div>
                </form>
            </div>
        </div>
    `,
    styles: [
        `
            @use '../../../styles/node-panel-mixins.scss' as mixins;

            .panel-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 0;
            }

            .panel-content {
                @include mixins.panel-content;
            }

            .form-container {
                @include mixins.form-container;
            }

            .field {
                display: flex;
                flex-direction: column;
            
            }

            .field label {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                font-size: 14px;
                color: rgba(255, 255, 255, 0.7);
                font-weight: 500;
                margin-bottom: 0.5rem;
            }

            .tooltip-icon {
                font-size: 16px;
                color: rgba(255, 255, 255, 0.5);
                cursor: help;
            }

            .select-field {
                width: 100%;
                padding: 0.5rem;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                color: rgba(255, 255, 255, 0.9);
                font-size: 14px;
                transition: border-color 0.2s ease;
                cursor: pointer;
            }

            .select-field:focus {
                outline: none;
                border-color: #00bfa5;
            }

            .select-field option {
                background: #1a1a1a;
                color: rgba(255, 255, 255, 0.9);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SubGraphNodePanelComponent extends BaseSidePanel<SubGraphNodeModel> implements OnInit {
    private flowsApiService = inject(FlowsApiService);
    
    public availableFlows = signal<GraphDto[]>([]);
    public readonly currentFlowId = input<number | null>(null);
    public readonly filteredFlows = computed(() => {
        const currentId = this.currentFlowId();
        if (!currentId) {
            return this.availableFlows();
        }
        return this.availableFlows().filter((flow) => flow.id !== currentId);
    });

    constructor() {
        super();
    }

    public get activeColor(): string {
        return this.node().color || '#00bfa5';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    ngOnInit(): void {
        this.flowsApiService.getGraphsLight().subscribe({
            next: (flows: any[]) => {
                this.availableFlows.set(flows);
            },
            error: (err) => console.error('Error fetching flows:', err),
        });
    }

    protected initializeForm(): FormGroup {
        const currentFlowId = this.currentFlowId();
        const selectedId = this.node().data.id ?? null;
        const initialSelectedId =
            currentFlowId && selectedId === currentFlowId ? null : selectedId;

        const form = this.fb.group({
            node_name: [this.node().node_name || '', this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            selectedFlowId: [initialSelectedId, Validators.required],
        });

        this.initializeInputMap(form);
        return form;
    }

    public onFlowChange(): void {
    }

    protected createUpdatedNode(): SubGraphNodeModel {
        const selectedId = this.form.get('selectedFlowId')?.value;
        const selectedFlow = this.availableFlows().find(f => f.id === Number(selectedId));
        
        let updatedData = this.node().data;
        if (selectedFlow) {
            updatedData = {
                id: selectedFlow.id,
                name: selectedFlow.name,
                description: selectedFlow.description,
                tags: selectedFlow.tags || [],
            };
        }

        const validInputPairs = this.getValidInputPairs();
        const inputMapValue = this.createInputMapFromPairs(validInputPairs);

        return {
            ...this.node(),
            node_name: this.form.get('node_name')?.value || this.node().node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: updatedData,
        };
    }

    private initializeInputMap(form: FormGroup): void {
        const inputMapArray = form.get('input_map') as FormArray;

        if (
            this.node().input_map &&
            Object.keys(this.node().input_map).length > 0
        ) {
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

    private getValidInputPairs(): any[] {
        return this.inputMapPairs.controls.filter((control) => {
            const value = control.value;
            return value.key?.trim() !== '' || value.value?.trim() !== '';
        });
    }

    private createInputMapFromPairs(pairs: any[]): Record<string, string> {
        return pairs.reduce((acc: Record<string, string>, curr: any) => {
            const pair = curr.value as InputMapPair;
            if (pair.key?.trim()) {
                acc[pair.key.trim()] = pair.value;
            }
            return acc;
        }, {});
    }
}

