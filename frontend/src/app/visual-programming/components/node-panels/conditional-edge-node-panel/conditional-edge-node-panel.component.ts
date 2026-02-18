import {
    ChangeDetectionStrategy,
    Component,
    input,
    signal,
} from '@angular/core';
import {
    ReactiveFormsModule,
    FormGroup,
    Validators,
    FormArray,
    FormBuilder,
} from '@angular/forms';
import { EdgeNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { CommonModule } from '@angular/common';

interface InputMapPair {
    key: string;
    value: string;
}

@Component({
    standalone: true,
    selector: 'app-conditional-edge-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        CodeEditorComponent,
        CommonModule,
    ],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">                   
                    @if (!isExpanded() || isFormFieldsVisible()) {
                        <!-- Node Name Field -->
                        <app-custom-input
                            label="Node Name"
                            tooltipText="The unique identifier used to reference this conditional edge. This name must be unique within the flow."
                            formControlName="node_name"
                            placeholder="Enter node name"
                            [activeColor]="activeColor"
                            [errorMessage]="getNodeNameErrorMessage()"
                        ></app-custom-input>

                        <!-- Input Map Key-Value Pairs -->
                        <div class="input-map">
                            <app-input-map
                                [activeColor]="activeColor"
                            ></app-input-map>
                        </div>

                        <!-- Libraries Input -->
                        <app-custom-input
                            label="Libraries"
                            tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                            formControlName="libraries"
                            placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                            [activeColor]="activeColor"
                        ></app-custom-input>
                    }

                    <!-- Code Editor Section with Toggle Button -->
                    @if (isExpanded()) {
                        <div class="code-editor-container">
                            <button
                                type="button"
                                class="toggle-fields-button"
                                [class.toggle-fields-button--inside]="
                                    !isFormFieldsVisible()
                                "
                                (click)="toggleFormFieldsVisibility()"
                                [attr.aria-label]="
                                    isFormFieldsVisible()
                                        ? 'Hide form fields'
                                        : 'Show form fields'
                                "
                            >
                                <svg
                                    width="20"
                                    height="12"
                                    viewBox="0 0 20 12"
                                    fill="none"
                                    xmlns="http://www.w3.org/2000/svg"
                                    [style.transform]="
                                        isFormFieldsVisible()
                                            ? 'scaleY(1)'
                                            : 'scaleY(-1)'
                                    "
                                >
                                    <path
                                        d="M1 11L10 1L19 11"
                                        stroke="currentColor"
                                        stroke-width="2"
                                        stroke-linecap="round"
                                        stroke-linejoin="round"
                                    />
                                </svg>
                            </button>
                            <div
                                class="code-editor-section"
                                [class.fields-hidden]="!isFormFieldsVisible()"
                            >
                                <app-code-editor
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="
                                        onPythonCodeChange($event)
                                    "
                                    (errorChange)="onCodeErrorChange($event)"
                                ></app-code-editor>
                            </div>
                        </div>
                    } @else {
                        <!-- Code Editor Section without Toggle Button (collapsed mode) -->
                        <div class="code-editor-section">
                            <app-code-editor
                                [pythonCode]="pythonCode"
                                (pythonCodeChange)="onPythonCodeChange($event)"
                                (errorChange)="onCodeErrorChange($event)"
                            ></app-code-editor>
                        </div>
                    }
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
                height: 100%;
                min-height: 0;
                display: flex;
                flex-direction: column;
            }

            .section-header {
                @include mixins.section-header;
            }

            .form-container {
                @include mixins.form-container;
                height: 100%;
                min-height: 0;
                display: flex;
                flex-direction: column;
                gap: 1rem;
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
            }

            .code-editor-container {
                position: relative;
                display: flex;
                flex-direction: column;
                flex: 1;
                height: 100%;
                min-height: 0;
            }

            .toggle-fields-button {
                width: 66px;
                height: 28px;
                display: flex;
                align-items: center;
                justify-content: center;               
                background: transparent;
                cursor: pointer;               
                transition: all 0.2s ease;
                padding: 0;
                color: #d9d9d999;
                z-index: 10;

                svg {
                    transition: transform 0.3s ease;
                }

                &:hover:not(:disabled) {
                    color: #d9d9d9;
                    background: #2c2c2e;
                }

                &:active:not(:disabled) {
                    color: #d9d9d9;                   
                }

                &:disabled {
                    cursor: not-allowed;
                    opacity: 0.5;
                }
                
                &:not(.toggle-fields-button--inside) {
                    align-self: center;
                    border-width: 1px 1px 0px 1px;
                    border-radius: 8px 8px 0 0;
                    border-style: solid;
                    border-color: #2c2c2e;
                }
                
                &.toggle-fields-button--inside {
                    position: absolute;
                    top: 0;
                    left: 50%;
                    transform: translateX(-50%);                   
                    border-width: 0 1px 1px 1px;
                    border-radius: 0 0 8px 8px;
                    border-style: solid;
                    border-color: #2c2c2e;
                }
            }

            .code-editor-section {
                height: 300px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
                flex: 1;
                display: flex;
                flex-direction: column;
                position: relative;               
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConditionalEdgeNodePanelComponent extends BaseSidePanel<EdgeNodeModel> {
    public readonly isExpanded = input<boolean>(false);
    public readonly isFormFieldsVisible = signal<boolean>(true);

    public pythonCode: string = '';
    public initialPythonCode: string = '';
    public codeEditorHasError: boolean = false;

    constructor() {
        super();
    }

    public get activeColor(): string {
        return this.node().color || '#685fff';
    }

    public get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    public onPythonCodeChange(code: string): void {
        this.pythonCode = code;
    }

    public onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    public toggleFormFieldsVisibility(): void {
        this.isFormFieldsVisible.update((value) => !value);
    }

    /**
     * This single method now implements the `initializeForm` requirement from the base class.
     * It is responsible for both defining the form's structure and populating
     * it with the initial data from the node signal.
     */
    protected initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            libraries: [
                this.node().data.python_code.libraries?.join(', ') || '',
            ],
        });

        // Initialize input map with existing data
        this.initializeInputMap(form);

        // Initialize Python code
        this.pythonCode = this.node().data.python_code.code || '';
        this.initialPythonCode = this.pythonCode;

        return form;
    }

    /**
     * This method remains the same, providing the specific data payload
     * for a ConditionalEdgeNode when the inherited onSave() method is called.
     */
    protected createUpdatedNode(): EdgeNodeModel {
        const validInputPairs = this.getValidInputPairs();
        const inputMapValue = this.createInputMapFromPairs(validInputPairs);

        // Parse libraries from comma-separated string
        const librariesArray = this.form.value.libraries
            ? this.form.value.libraries
                  .split(',')
                  .map((lib: string) => lib.trim())
                  .filter((lib: string) => lib.length > 0)
            : [];

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...this.node().data,
                source: this.node().data.source,
                then: this.node().data.then,
                python_code: {
                    ...this.node().data.python_code,
                    name:
                        this.node().data.python_code.name ||
                        'Conditional Edge Code',
                    code: this.pythonCode,
                    entrypoint: 'main',
                    libraries: librariesArray,
                },
            },
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
                    }),
                );
            });
        } else {
            inputMapArray.push(
                this.fb.group({
                    key: [''],
                    value: ['variables.'],
                }),
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
