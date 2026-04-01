import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, effect, signal } from '@angular/core';
import { output } from '@angular/core';
import { AbstractControl, FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { ProjectNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { InputMapComponent } from '../../input-map/input-map.component';

interface InputMapPair {
    key: string;
    value: string;
}

@Component({
    standalone: true,
    selector: 'app-project-node-panel',
    imports: [ReactiveFormsModule, CustomInputComponent, InputMapComponent, CommonModule],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">
                    <app-custom-input
                        label="Node Name"
                        tooltipText="The unique identifier used to reference this project node. This name must be unique within the flow."
                        formControlName="node_name"
                        placeholder="Enter node name"
                        [activeColor]="activeColor"
                        [errorMessage]="getNodeNameErrorMessage()"
                    ></app-custom-input>

                    <div class="input-map">
                        <app-input-map [activeColor]="activeColor"></app-input-map>
                    </div>

                    <app-custom-input
                        label="Output Variable Path"
                        tooltipText="The path where the output of this node will be stored in your flow variables. Leave empty if you don't need to store the output."
                        formControlName="output_variable_path"
                        placeholder="Enter output variable path (leave empty for null)"
                        [activeColor]="activeColor"
                    ></app-custom-input>

                    <!-- <div class="stream-config-section" formGroupName="stream_config">
                        <span class="section-label">Streaming to EpicChat</span>
                        <div class="checkbox-list">
                            <label class="checkbox-item">
                                <input type="checkbox" formControlName="agent_activity" [style.accent-color]="activeColor" />
                                <span>Agent activity</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="checkbox" formControlName="task_progress" [style.accent-color]="activeColor" />
                                <span>Task progress</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="checkbox" formControlName="agent_reasoning" [style.accent-color]="activeColor" />
                                <span>Agent reasoning</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="checkbox" formControlName="tool_calls" [style.accent-color]="activeColor" />
                                <span>Tool calls</span>
                            </label>
                            <label class="checkbox-item">
                                <input type="checkbox" formControlName="final_reply" [style.accent-color]="activeColor" />
                                <span>Final reply</span>
                            </label>
                        </div>
                    </div> -->
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
                z-index: 1000;
            }

            .panel-content {
                @include mixins.panel-content;
            }

            .form-container {
                @include mixins.form-container;
            }

            .status-section {
                margin-top: 1rem;
                padding: 1rem;
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background-color: #f9f9f9;
            }

            .status-section h4 {
                margin: 0 0 0.5rem 0;
                color: #333;
            }

            .section-label {
                font-size: 0.75rem;
                color: #d9d9d999;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

            .stream-config-section {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .checkbox-list {
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
            }

            .checkbox-item {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                font-size: 0.85rem;
                color: #d4d4d4;
                cursor: pointer;

                input[type='checkbox'] {
                    width: 16px;
                    height: 16px;
                    cursor: pointer;
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectNodePanelComponent extends BaseSidePanel<ProjectNodeModel> {
    constructor() {
        super();
    }

    public get activeColor(): string {
        return this.node().color || '#685fff';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    protected initializeForm(): FormGroup {
        const sc = this.node().stream_config;
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            stream_config: this.fb.group({
                agent_activity: [sc?.['agent_activity'] ?? true],
                task_progress: [sc?.['task_progress'] ?? true],
                agent_reasoning: [sc?.['agent_reasoning'] ?? true],
                final_reply: [sc?.['final_reply'] ?? true],
                tool_calls: [sc?.['tool_calls'] ?? true],
            }),
        });

        this.initializeInputMap(form);
        return form;
    }

    protected createUpdatedNode(): ProjectNodeModel {
        const validInputPairs = this.getValidInputPairs();
        const inputMapValue = this.createInputMapFromPairs(validInputPairs);

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            stream_config: this.form.value.stream_config || {},
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

    private getValidInputPairs(): AbstractControl[] {
        return this.inputMapPairs.controls.filter((control) => {
            const value = control.value;
            return value.key?.trim() !== '' || value.value?.trim() !== '';
        });
    }

    private createInputMapFromPairs(pairs: AbstractControl[]): Record<string, string> {
        return pairs.reduce((acc: Record<string, string>, curr: AbstractControl) => {
            const pair = curr.value as InputMapPair;
            if (pair.key?.trim()) {
                acc[pair.key.trim()] = pair.value;
            }
            return acc;
        }, {});
    }
}
