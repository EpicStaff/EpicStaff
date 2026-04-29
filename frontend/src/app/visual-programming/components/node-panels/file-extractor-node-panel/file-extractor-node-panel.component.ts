import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { AbstractControl, FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { InputMapComponent } from '../../input-map/input-map.component';
interface InputMapPair {
    key: string;
    value: string;
}
@Component({
    standalone: true,
    selector: 'app-file-extractor-node-panel',
    imports: [ReactiveFormsModule, CustomInputComponent, InputMapComponent, CommonModule],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form
                    [formGroup]="form"
                    class="form-container"
                >
                    <!-- Node Name Field -->
                    <app-custom-input
                        label="Node Name"
                        tooltipText="The unique identifier used to reference this File Extractor node. This name must be unique within the flow."
                        formControlName="node_name"
                        placeholder="Enter node name"
                        [activeColor]="activeColor"
                        [errorMessage]="getNodeNameErrorMessage()"
                    ></app-custom-input>

                    <!-- Input Map Key-Value Pairs -->
                    <div class="input-map">
                        <app-input-map [activeColor]="activeColor"></app-input-map>
                    </div>

                    <!-- Output Variable Path -->
                    <app-custom-input
                        label="Output Variable Path"
                        tooltipText="The path where the output of this node will be stored in your flow variables. Leave empty if you don't need to store the output."
                        formControlName="output_variable_path"
                        placeholder="Enter output variable path (leave empty for null)"
                        [activeColor]="activeColor"
                    ></app-custom-input>
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

            .section-header {
                @include mixins.section-header;
            }

            .form-container {
                @include mixins.form-container;
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FileExtractorNodePanelComponent extends BaseSidePanel<FileExtractorNodeModel> {
    constructor() {
        super();
    }

    public get activeColor(): string {
        return this.node().color || '#2196F3';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    protected initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
        });

        this.initializeInputMap(form);

        return form;
    }

    protected createUpdatedNode(): FileExtractorNodeModel {
        const validInputPairs = this.getValidInputPairs();
        const inputMapValue = this.createInputMapFromPairs(validInputPairs);

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
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
            const value = control.value as InputMapPair;
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
