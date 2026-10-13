import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AbstractControl, FormArray, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { CustomInputComponent, ValidationErrorsComponent } from '@shared/components';

import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SandboxLimitsStorageService } from '../../../services/sandbox-limits-storage.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import {
    createExecutionTimeoutField,
    ExecutionTimeoutFormField,
} from '../shared/execution-timeout-field/execution-timeout-control';
import { ExecutionTimeoutFieldComponent } from '../shared/execution-timeout-field/execution-timeout-field.component';
interface InputMapPair {
    key: string;
    value: string;
}
@Component({
    selector: 'app-file-extractor-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        ValidationErrorsComponent,
        ExecutionTimeoutFieldComponent,
    ],
    templateUrl: './file-extractor-node-panel.component.html',
    styleUrls: ['./file-extractor-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FileExtractorNodePanelComponent extends BaseSidePanel<FileExtractorNodeModel> {
    protected executionTimeout!: ExecutionTimeoutFormField;

    private readonly sandboxLimits = inject(SandboxLimitsStorageService);

    constructor() {
        super();
    }

    public get activeColor(): string {
        return 'var(--accent-color)';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    protected initializeForm(): FormGroup {
        this.executionTimeout = createExecutionTimeoutField(
            this.node().execution_timeout,
            this.sandboxLimits.maxExecutionTimeoutMinutes()
        );
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            execution_timeout: this.executionTimeout.control,
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
            execution_timeout: this.executionTimeout.control.value,
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
