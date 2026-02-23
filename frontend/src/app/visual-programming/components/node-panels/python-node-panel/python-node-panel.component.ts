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
import { PythonNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { CommonModule } from '@angular/common';
import { SidePanelService } from '../../../services/side-panel.service';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { expandCollapseAnimation } from '../../../../shared/animations/animations-expand-collapse';

interface InputMapPair {
    key: string;
    value: string;
}

@Component({
    standalone: true,
    selector: 'app-python-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        CodeEditorComponent,
        CommonModule,
    ],
    animations: [expandCollapseAnimation],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">
                    @if (isExpanded()) {
                        <!-- Expanded Mode: Two Column Layout or Full Width -->
                        <div
                            class="form-layout expanded"
                            [class.code-editor-fullwidth]="
                                isCodeEditorFullWidth()
                            "
                        >
                            <!-- Left Column - Form Fields -->
                            @if (!isCodeEditorFullWidth()) {
                                <div class="form-fields">
                                    <!-- Node Name Field -->
                                    <app-custom-input
                                        label="Node Name"
                                        tooltipText="The unique identifier used to reference this Python node. This name must be unique within the flow."
                                        formControlName="node_name"
                                        placeholder="Enter node name"
                                        [activeColor]="activeColor"
                                        [errorMessage]="
                                            getNodeNameErrorMessage()
                                        "
                                    ></app-custom-input>

                                    <!-- Input Map Key-Value Pairs -->
                                    <div class="input-map">
                                        <app-input-map
                                            [activeColor]="activeColor"
                                        ></app-input-map>
                                    </div>

                                    <!-- Output Variable Path -->
                                    <app-custom-input
                                        label="Output Variable Path"
                                        tooltipText="The path where the output of this node will be stored in your flow variables. Leave empty if you don't need to store the output."
                                        formControlName="output_variable_path"
                                        placeholder="Enter output variable path (leave empty for null)"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>

                                    <!-- Libraries Input -->
                                    <app-custom-input
                                        label="Libraries"
                                        tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                                        formControlName="libraries"
                                        placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>
                                </div>
                            }

                            <!-- Code Editor Section with Toggle Arrow -->
                            <div class="code-editor-wrapper">
                                <button
                                    type="button"
                                    class="toggle-icon-button"
                                    (click)="toggleCodeEditorFullWidth()"
                                    [attr.aria-label]="
                                        isCodeEditorFullWidth()
                                            ? 'Collapse code editor'
                                            : 'Expand code editor'
                                    "
                                >
                                    <svg
                                        width="9"
                                        height="22"
                                        viewBox="0 0 9 22"
                                        fill="none"
                                        xmlns="http://www.w3.org/2000/svg"
                                        [style.transform]="
                                            isCodeEditorFullWidth()
                                                ? 'scaleX(1)'
                                                : 'scaleX(-1)'
                                        "
                                    >
                                        <path
                                            d="M7.16602 21.0001L1.16602 11.0001L7.16602 1.00012"
                                            stroke="currentColor"
                                            stroke-width="2"
                                            stroke-linecap="round"
                                        />
                                    </svg>
                                </button>

                                <app-code-editor
                                    class="code-editor-section"
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="
                                        onPythonCodeChange($event)
                                    "
                                    (errorChange)="onCodeErrorChange($event)"
                                ></app-code-editor>
                            </div>
                        </div>
                    } @else {
                        <!-- Collapsed Mode: Single Column Layout -->
                        <div class="form-layout collapsed">
                            <!-- Node Name Field -->
                            <app-custom-input
                                label="Node Name"
                                tooltipText="The unique identifier used to reference this Python node. This name must be unique within the flow."
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

                            <!-- Output Variable Path -->
                            <app-custom-input
                                label="Output Variable Path"
                                tooltipText="The path where the output of this node will be stored in your flow variables. Leave empty if you don't need to store the output."
                                formControlName="output_variable_path"
                                placeholder="Enter output variable path (leave empty for null)"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <!-- Libraries Input -->
                            <app-custom-input
                                label="Libraries"
                                tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                                formControlName="libraries"
                                placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <!-- Code Editor Section -->
                            <div class="code-editor-section">
                                <app-code-editor
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="
                                        onPythonCodeChange($event)
                                    "
                                    (errorChange)="onCodeErrorChange($event)"
                                ></app-code-editor>
                            </div>
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
            }

            .form-layout {
                height: 100%;
                min-height: 0;
                width: 100%;
                overflow: hidden;

                &.expanded {
                    display: flex;
                    gap: 1rem;
                    height: 100%;
                    width: 100%;

                    &.code-editor-fullwidth {
                        .form-fields {
                            display: none;
                        }

                        .code-editor-wrapper {
                            width: 100%;
                        }

                        .toggle-icon-button {
                            position: absolute;
                            left: 0;
                            top: 50%;
                            transform: translateY(-50%);
                            z-index: 10;
                            border-width: 1px 1px 1px 0px;
                            border-radius: 0 8px 8px 0;
                        }
                    }
                }

                &.collapsed {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                }
            }

            .form-fields {
                display: flex;
                flex-direction: column;
                gap: 1rem;
                flex: 0 0 400px;
                max-width: 400px;
                height: 100%;
                overflow-y: auto;
            }

            .code-editor-wrapper {
                display: flex;
                align-items: center;
                gap: 0;
                height: 100%;
                position: relative;
                flex: 1;
                min-height: 0;
                min-width: 0;
                transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);

                .toggle-icon-button {
                    flex-shrink: 0;
                    width: 28px;
                    height: 66px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border-width: 1px 0px 1px 1px;
                    border-style: solid;
                    border-color: #2c2c2e;
                    background: transparent;
                    cursor: pointer;
                    border-radius: 8px 0 0 8px;
                    transition: all 0.2s ease;
                    padding: 0;
                    color: #d9d9d999;

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
                }

                app-code-editor {
                    min-width: 0;
                }
            }

            .code-editor-section {
                border: 1px solid
                    var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-radius: 0 8px 8px 0;
                overflow: hidden;
                display: flex;
                flex-direction: column;               

                .expanded & {
                    flex: 1;
                    height: 100%;
                    min-height: 0;
                    transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
                    transform: scaleX(0.3) translateX(-50px);
                    opacity: 0;
                }

                .collapsed & {
                    height: 300px;
                }

                .form-layout.expanded:not(.code-editor-fullwidth) & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
                }

                .form-layout.expanded.code-editor-fullwidth & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
                }
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
export class PythonNodePanelComponent extends BaseSidePanel<PythonNodeModel> {
    public readonly isExpanded = input<boolean>(false);
    public readonly isCodeEditorFullWidth = signal<boolean>(true);

    pythonCode: string = '';
    initialPythonCode: string = '';
    codeEditorHasError: boolean = false;
    private readonly pythonCodeChange$ = new Subject<string>();

    constructor(private readonly sidePanelService: SidePanelService) {
        super();
        this.pythonCodeChange$
            .pipe(debounceTime(300), takeUntilDestroyed())
            .subscribe(() => {
                this.sidePanelService.triggerAutosave();
            });
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
        this.pythonCodeChange$.next(code);
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    initializeForm(): FormGroup {
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            libraries: [this.node().data.libraries?.join(', ') || ''],
        });

        this.initializeInputMap(form);

        this.pythonCode = this.node().data.code || '';
        this.initialPythonCode = this.pythonCode;

        return form;
    }

    createUpdatedNode(): PythonNodeModel {
        const validInputPairs = this.getValidInputPairs();
        const inputMapValue = this.createInputMapFromPairs(validInputPairs);

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
                name: this.node().data.name || 'Python Code',
                code: this.pythonCode,
                entrypoint: 'main',
                libraries: librariesArray,
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

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((value) => !value);
    }
}
