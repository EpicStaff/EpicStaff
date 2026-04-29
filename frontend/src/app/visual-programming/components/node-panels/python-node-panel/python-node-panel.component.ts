import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { expandCollapseAnimation } from '../../../../shared/animations/animations-expand-collapse';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { PythonNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { NodeStorageSectionComponent } from '../../node-storage-section/node-storage-section.component';
import {
    createInputMapFromPairs,
    getValidInputPairs,
    initializeInputMap,
    parseCommaSeparatedList,
} from '../node-panel-form.utils';

@Component({
    standalone: true,
    selector: 'app-python-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        CodeEditorComponent,
        CommonModule,
        NodeStorageSectionComponent,
        AppSvgIconComponent,
    ],
    animations: [expandCollapseAnimation],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form
                    [formGroup]="form"
                    class="form-container"
                >
                    @if (isExpanded()) {
                        <div
                            class="form-layout expanded"
                            [class.code-editor-fullwidth]="isCodeEditorFullWidth()"
                        >
                            @if (!isCodeEditorFullWidth()) {
                                <div class="form-fields">
                                    <app-custom-input
                                        label="Node Name"
                                        tooltipText="The unique identifier used to reference this Python node. This name must be unique within the flow."
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

                                    <app-custom-input
                                        label="Libraries"
                                        tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                                        formControlName="libraries"
                                        placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>

                                    <div
                                        class="stream-config-section"
                                        formGroupName="stream_config"
                                    >
                                        <span class="section-label">Streaming to EpicChat</span>
                                        <div class="checkbox-list">
                                            <label class="checkbox-item">
                                                <input
                                                    type="checkbox"
                                                    formControlName="execution_status"
                                                />
                                                <span>Execution status</span>
                                            </label>
                                        </div>
                                    </div>

                                    <app-node-storage-section
                                        [useStorage]="useStorage()"
                                        (onToggleChange)="onStorageToggle($event)"
                                        (onInsertCode)="insertStorageCode($event)"
                                        (onRemoveCode)="removeStorageCode($event)"
                                    ></app-node-storage-section>
                                </div>
                            }

                            <div class="code-editor-wrapper">
                                <button
                                    type="button"
                                    class="toggle-icon-button"
                                    (click)="toggleCodeEditorFullWidth()"
                                    [attr.aria-label]="
                                        isCodeEditorFullWidth() ? 'Collapse code editor' : 'Expand code editor'
                                    "
                                >
                                    <app-svg-icon
                                        [icon]="isCodeEditorFullWidth() ? 'chevron-right' : 'chevron-left'"
                                        size="1rem"
                                    ></app-svg-icon>
                                </button>

                                <app-code-editor
                                    class="code-editor-section"
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="onPythonCodeChange($event)"
                                    (errorChange)="onCodeErrorChange($event)"
                                ></app-code-editor>
                            </div>
                        </div>
                    } @else {
                        <div class="form-layout collapsed">
                            <app-custom-input
                                label="Node Name"
                                tooltipText="The unique identifier used to reference this Python node. This name must be unique within the flow."
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

                            <app-custom-input
                                label="Libraries"
                                tooltipText="Python libraries required by this code (comma-separated). For example: requests, pandas, numpy"
                                formControlName="libraries"
                                placeholder="Enter libraries (e.g., requests, pandas, numpy)"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <div
                                class="stream-config-section"
                                formGroupName="stream_config"
                            >
                                <span class="section-label">Streaming to EpicChat</span>
                                <div class="checkbox-list">
                                    <label class="checkbox-item">
                                        <input
                                            type="checkbox"
                                            formControlName="execution_status"
                                        />
                                        <span>Execution status</span>
                                    </label>
                                </div>
                            </div>

                            <app-node-storage-section
                                [useStorage]="useStorage()"
                                (onToggleChange)="onStorageToggle($event)"
                                (onInsertCode)="insertStorageCode($event)"
                                (onRemoveCode)="removeStorageCode($event)"
                            ></app-node-storage-section>

                            <div class="code-editor-section">
                                <app-code-editor
                                    [pythonCode]="pythonCode"
                                    (pythonCodeChange)="onPythonCodeChange($event)"
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
                        overflow: visible;

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
                    overflow: visible;
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
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-radius: 0 8px 8px 0;
                overflow: visible;
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
                    flex-shrink: 0;
                }

                .form-layout.expanded:not(.code-editor-fullwidth) & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
                }

                .form-layout.expanded.code-editor-fullwidth & {
                    transform: scaleX(1) translateX(0);
                    opacity: 1;
                    overflow: visible;
                }
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
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
export class PythonNodePanelComponent extends BaseSidePanel<PythonNodeModel> {
    public override readonly isExpanded = input<boolean>(false);
    public readonly isCodeEditorFullWidth = signal<boolean>(true);
    public readonly useStorage = signal<boolean>(false);

    pythonCode: string = '';
    codeEditorHasError: boolean = false;
    private readonly pythonCodeChange$ = new Subject<string>();

    constructor(private readonly sidePanelService: SidePanelService) {
        super();
        this.pythonCodeChange$.pipe(debounceTime(300), takeUntilDestroyed()).subscribe(() => {
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

    onStorageToggle(value: boolean): void {
        this.useStorage.set(value);
        this.sidePanelService.triggerAutosave();
    }

    insertStorageCode(code: string): void {
        if (!this.pythonCode.includes('epicstaff_storage')) {
            this.pythonCode = code + '\n\n' + this.pythonCode;
        }
        this.sidePanelService.triggerAutosave();
    }

    removeStorageCode(code: string): void {
        const prefix = code + '\n\n';
        if (this.pythonCode.startsWith(prefix)) {
            this.pythonCode = this.pythonCode.slice(prefix.length);
            this.sidePanelService.triggerAutosave();
        }
    }

    initializeForm(): FormGroup {
        const sc = this.node().stream_config;

        this.useStorage.set(this.node().data.use_storage ?? false);

        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            libraries: [this.node().data.libraries?.join(', ') || ''],
            stream_config: this.fb.group({
                execution_status: [sc?.['execution_status'] ?? true],
            }),
        });

        this.initializeInputMap(form);

        this.pythonCode = this.node().data.code || '';

        return form;
    }

    createUpdatedNode(): PythonNodeModel {
        const validInputPairs = getValidInputPairs(this.inputMapPairs);
        const inputMapValue = createInputMapFromPairs(validInputPairs);
        const librariesArray = parseCommaSeparatedList(this.form.value.libraries);

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
                use_storage: this.useStorage(),
            },
            stream_config: this.form.value.stream_config || {},
        };
    }

    private initializeInputMap(form: FormGroup): void {
        initializeInputMap(form, this.node().input_map as Record<string, unknown> | null | undefined, this.fb);
    }

    toggleCodeEditorFullWidth(): void {
        this.isCodeEditorFullWidth.update((value) => !value);
    }
}
