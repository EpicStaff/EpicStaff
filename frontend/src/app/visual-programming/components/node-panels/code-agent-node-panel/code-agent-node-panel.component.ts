import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
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
import { CodeAgentNodeModel } from '../../../core/models/node.model';
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
import { FullLLMConfigService, FullLLMConfig } from '../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';
import { DEFAULT_OUTPUT_SCHEMA } from './default-output-schema';

interface InputMapPair {
    key: string;
    value: string;
}

@Component({
    standalone: true,
    selector: 'app-code-agent-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        CodeEditorComponent,
        CommonModule,
        JsonEditorComponent,
    ],
    animations: [expandCollapseAnimation],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form [formGroup]="form" class="form-container">
                    @if (isExpanded()) {
                        <div
                            class="form-layout expanded"
                            [class.code-editor-fullwidth]="
                                isCodeEditorFullWidth()
                            "
                        >
                            @if (!isCodeEditorFullWidth()) {
                                <div class="form-fields">
                                    <app-custom-input
                                        label="Node Name"
                                        tooltipText="Unique identifier for this Code Agent node within the flow."
                                        formControlName="node_name"
                                        placeholder="Enter node name"
                                        [activeColor]="activeColor"
                                        [errorMessage]="
                                            getNodeNameErrorMessage()
                                        "
                                    ></app-custom-input>

                                    <div class="input-map">
                                        <app-input-map
                                            [activeColor]="activeColor"
                                        ></app-input-map>
                                    </div>

                                    <app-custom-input
                                        label="Output Variable Path"
                                        tooltipText="Path where the Code Agent output will be stored in flow variables."
                                        formControlName="output_variable_path"
                                        placeholder="e.g. code_reply"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>

                                    <div class="select-field">
                                        <label class="select-label">Agent Mode</label>
                                        <select formControlName="agent_mode" class="select-input" [style.--active-color]="activeColor">
                                            <option value="build">Build</option>
                                            <option value="plan">Plan</option>
                                        </select>
                                    </div>

                                    <div class="select-field">
                                        <label class="select-label">LLM Config</label>
                                        <select formControlName="llm_config" class="select-input" [style.--active-color]="activeColor">
                                            <option [ngValue]="null">— None —</option>
                                            @for (cfg of llmConfigs; track cfg.id) {
                                                <option [ngValue]="cfg.id">{{ cfg.custom_name || ('Config #' + cfg.id) }}</option>
                                            }
                                        </select>
                                    </div>

                                    <app-custom-input
                                        label="Session ID"
                                        tooltipText="Variable path for the OpenCode session ID (e.g. variables.chat_id). Each unique value gets its own session with its own system prompt."
                                        formControlName="session_id"
                                        placeholder="e.g. variables.chat_id"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>

                                    <app-custom-input
                                        label="System Prompt"
                                        tooltipText="System prompt sent to the Code Agent before the user message."
                                        formControlName="system_prompt"
                                        placeholder="Enter system prompt"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>

                                    <div class="timeout-section">
                                        <span class="section-label">Timeouts</span>
                                        <div class="timeout-grid">
                                            <app-custom-input
                                                label="Poll (ms)"
                                                formControlName="polling_interval_ms"
                                                [activeColor]="activeColor"
                                            ></app-custom-input>
                                            <app-custom-input
                                                label="Chunk Timeout (s)"
                                                formControlName="chunk_timeout_s"
                                                [activeColor]="activeColor"
                                            ></app-custom-input>
                                            <app-custom-input
                                                label="Inactivity (s)"
                                                formControlName="inactivity_timeout_s"
                                                [activeColor]="activeColor"
                                            ></app-custom-input>
                                            <app-custom-input
                                                label="Max Wait (s)"
                                                formControlName="max_wait_s"
                                                [activeColor]="activeColor"
                                            ></app-custom-input>
                                        </div>
                                    </div>

                                    <div class="stream-config-section" formGroupName="stream_config">
                                        <span class="section-label">Streaming to EpicChat</span>
                                        <div class="checkbox-list">
                                            <label class="checkbox-item">
                                                <input type="checkbox" formControlName="reasoning" [style.accent-color]="activeColor" />
                                                <span>Reasoning</span>
                                            </label>
                                            <label class="checkbox-item">
                                                <input type="checkbox" formControlName="tool_calls" [style.accent-color]="activeColor" />
                                                <span>Tool calls</span>
                                            </label>
                                            <label class="checkbox-item">
                                                <input type="checkbox" formControlName="tool_results" [style.accent-color]="activeColor" />
                                                <span>Tool results</span>
                                            </label>
                                            <label class="checkbox-item">
                                                <input type="checkbox" formControlName="final_reply" [style.accent-color]="activeColor" />
                                                <span>Final reply</span>
                                            </label>
                                        </div>
                                    </div>

                                    <app-custom-input
                                        label="Libraries"
                                        tooltipText="Python libraries for event hook callbacks (comma-separated)."
                                        formControlName="libraries"
                                        placeholder="e.g. requests, httpx"
                                        [activeColor]="activeColor"
                                    ></app-custom-input>
                                </div>
                            }

                            <div class="editor-panel-wrapper">
                                <button
                                    type="button"
                                    class="toggle-icon-button"
                                    (click)="toggleCodeEditorFullWidth()"
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

                                <div class="editor-panel">
                                    <div class="editor-tabs">
                                        <button
                                            type="button"
                                            class="editor-tab"
                                            [class.active]="activeEditorTab() === 'hooks'"
                                            [style.--accent-color]="activeColor"
                                            (click)="activeEditorTab.set('hooks')"
                                        >Event Hooks</button>
                                        <button
                                            type="button"
                                            class="editor-tab"
                                            [class.active]="activeEditorTab() === 'schema'"
                                            [style.--accent-color]="activeColor"
                                            (click)="activeEditorTab.set('schema')"
                                        >Output Schema</button>
                                    </div>
                                    <div class="editor-tab-content">
                                        @switch (activeEditorTab()) {
                                            @case ('hooks') {
                                                <app-code-editor
                                                    class="code-editor-section"
                                                    [pythonCode]="streamHandlerCode"
                                                    (pythonCodeChange)="onStreamHandlerCodeChange($event)"
                                                    (errorChange)="onCodeErrorChange($event)"
                                                ></app-code-editor>
                                            }
                                            @case ('schema') {
                                                <div class="schema-editor-container">
                                                    <app-json-editor
                                                        [jsonData]="outputSchemaText"
                                                        (jsonChange)="onSchemaEditorChange($event)"
                                                        (validationChange)="onSchemaValidChange($event)"
                                                        [fullHeight]="true"
                                                        [showHeader]="false"
                                                    ></app-json-editor>
                                                </div>
                                            }
                                        }
                                    </div>
                                </div>
                            </div>
                        </div>
                    } @else {
                        <div class="form-layout collapsed">
                            <app-custom-input
                                label="Node Name"
                                tooltipText="Unique identifier for this Code Agent node within the flow."
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
                                formControlName="output_variable_path"
                                placeholder="e.g. code_reply"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <div class="select-field">
                                <label class="select-label">Agent Mode</label>
                                <select formControlName="agent_mode" class="select-input" [style.--active-color]="activeColor">
                                    <option value="build">Build</option>
                                    <option value="plan">Plan</option>
                                </select>
                            </div>

                            <div class="select-field">
                                <label class="select-label">LLM Config</label>
                                <select formControlName="llm_config" class="select-input" [style.--active-color]="activeColor">
                                    <option [ngValue]="null">— None —</option>
                                    @for (cfg of llmConfigs; track cfg.id) {
                                        <option [ngValue]="cfg.id">{{ cfg.custom_name || ('Config #' + cfg.id) }}</option>
                                    }
                                </select>
                            </div>

                            <app-custom-input
                                label="Session ID"
                                tooltipText="Variable path for the OpenCode session ID."
                                formControlName="session_id"
                                placeholder="e.g. variables.chat_id"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <app-custom-input
                                label="System Prompt"
                                formControlName="system_prompt"
                                placeholder="Enter system prompt"
                                [activeColor]="activeColor"
                            ></app-custom-input>

                            <div class="stream-config-section" formGroupName="stream_config">
                                <span class="section-label">Streaming to EpicChat</span>
                                <div class="checkbox-list">
                                    <label class="checkbox-item">
                                        <input type="checkbox" formControlName="reasoning" [style.accent-color]="activeColor" />
                                        <span>Reasoning</span>
                                    </label>
                                    <label class="checkbox-item">
                                        <input type="checkbox" formControlName="tool_calls" [style.accent-color]="activeColor" />
                                        <span>Tool calls</span>
                                    </label>
                                    <label class="checkbox-item">
                                        <input type="checkbox" formControlName="tool_results" [style.accent-color]="activeColor" />
                                        <span>Tool results</span>
                                    </label>
                                    <label class="checkbox-item">
                                        <input type="checkbox" formControlName="final_reply" [style.accent-color]="activeColor" />
                                        <span>Final reply</span>
                                    </label>
                                </div>
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

                        .editor-panel-wrapper {
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

            .section-label {
                font-size: 0.75rem;
                color: #d9d9d999;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

            .timeout-section {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .timeout-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0.5rem;
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

            .select-field {
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
            }

            .select-label {
                font-size: 0.75rem;
                color: #d9d9d999;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

            .select-input {
                background: var(--color-nodes-background, #1e1e1e);
                color: #d4d4d4;
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-radius: 8px;
                padding: 0.5rem 0.75rem;
                font-size: 0.875rem;
                cursor: pointer;
                outline: none;
                appearance: auto;
                transition: border-color 0.2s ease;

                &:focus {
                    border-color: var(--active-color, #685fff);
                }

                option {
                    background: #1e1e1e;
                    color: #d4d4d4;
                }
            }

            .output-schema-section {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }

            .output-schema-textarea {
                background: var(--color-nodes-background, #1e1e1e);
                color: #d4d4d4;
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-radius: 8px;
                padding: 0.5rem 0.75rem;
                font-family: 'Fira Code', 'Consolas', monospace;
                font-size: 0.8rem;
                resize: vertical;
                outline: none;
                transition: border-color 0.2s ease;
                min-height: 80px;

                &:focus {
                    border-color: var(--active-color, #685fff);
                }

                &::placeholder {
                    color: #d9d9d944;
                }
            }

            .schema-error {
                font-size: 0.75rem;
                color: #ff6b6b;
            }

            .editor-panel-wrapper {
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
                }
            }

            .editor-panel {
                display: flex;
                flex-direction: column;
                flex: 1;
                height: 100%;
                min-height: 0;
                min-width: 0;
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-radius: 0 8px 8px 0;
                overflow: hidden;
                transition: all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);

                .expanded & {
                    transform: scaleX(0.3) translateX(-50px);
                    opacity: 0;
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

            .editor-tabs {
                display: flex;
                border-bottom: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                flex-shrink: 0;
            }

            .editor-tab {
                background: none;
                border: none;
                color: var(--color-text-secondary, #d9d9d999);
                font-size: 0.8rem;
                padding: 0.6rem 1.2rem;
                cursor: pointer;
                border-bottom: 2px solid transparent;
                transition: color 0.2s, border-bottom 0.2s;

                &:hover {
                    color: #ffffff;
                }

                &.active {
                    color: var(--color-text-primary, #d4d4d4);
                    border-bottom-color: var(--accent-color, #685fff);
                }
            }

            .editor-tab-content {
                flex: 1;
                min-height: 0;
                display: flex;
                flex-direction: column;
            }

            .code-editor-section {
                flex: 1;
                height: 100%;
                min-height: 0;
                display: flex;
                flex-direction: column;

                app-code-editor {
                    min-width: 0;
                }
            }

            .schema-editor-container {
                flex: 1;
                display: flex;
                flex-direction: column;
                min-height: 0;

                app-json-editor {
                    flex: 1;
                    height: 100%;
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CodeAgentNodePanelComponent extends BaseSidePanel<CodeAgentNodeModel> {
    public readonly isExpanded = input<boolean>(false);
    public readonly isCodeEditorFullWidth = signal<boolean>(true);
    public readonly activeEditorTab = signal<'hooks' | 'schema'>('hooks');

    streamHandlerCode: string = '';
    outputSchemaText: string = '';
    outputSchemaError: string = '';
    codeEditorHasError: boolean = false;
    llmConfigs: FullLLMConfig[] = [];
    private readonly codeChange$ = new Subject<string>();

    constructor(
        private readonly sidePanelService: SidePanelService,
        private readonly fullLLMConfigService: FullLLMConfigService,
        private readonly cdr: ChangeDetectorRef,
    ) {
        super();
        this.codeChange$
            .pipe(debounceTime(300), takeUntilDestroyed())
            .subscribe(() => {
                this.sidePanelService.triggerAutosave();
            });
        this.fullLLMConfigService.getFullLLMConfigs()
            .pipe(takeUntilDestroyed())
            .subscribe((configs) => {
                this.llmConfigs = configs;
                this.cdr.markForCheck();
            });
    }

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    onStreamHandlerCodeChange(code: string): void {
        this.streamHandlerCode = code;
        this.codeChange$.next(code);
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    onSchemaEditorChange(json: string): void {
        this.outputSchemaText = json;
        this.sidePanelService.triggerAutosave();
    }

    onSchemaValidChange(isValid: boolean): void {
        this.outputSchemaError = isValid ? '' : 'Invalid JSON';
    }

    initializeForm(): FormGroup {
        const data = this.node().data;
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            agent_mode: [data.agent_mode || 'build'],
            llm_config: [data.llm_config_id ?? null],
            session_id: [data.session_id || ''],
            system_prompt: [data.system_prompt || ''],
            libraries: [data.libraries?.join(', ') || ''],
            polling_interval_ms: [data.polling_interval_ms || 1000],
            chunk_timeout_s: [data.chunk_timeout_s || 30],
            inactivity_timeout_s: [data.inactivity_timeout_s || 120],
            max_wait_s: [data.max_wait_s || 300],
            stream_config: this.fb.group({
                reasoning: [this.node().stream_config?.['reasoning'] ?? true],
                tool_calls: [this.node().stream_config?.['tool_calls'] ?? true],
                tool_results: [this.node().stream_config?.['tool_results'] ?? true],
                final_reply: [this.node().stream_config?.['final_reply'] ?? true],
            }),
        });

        this.initializeInputMap(form);
        this.streamHandlerCode = data.stream_handler_code || '';
        const schema = data.output_schema;
        this.outputSchemaText = schema && Object.keys(schema).length > 0
            ? JSON.stringify(schema, null, 2)
            : JSON.stringify(DEFAULT_OUTPUT_SCHEMA, null, 2);

        return form;
    }

    createUpdatedNode(): CodeAgentNodeModel {
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
                agent_mode: this.form.value.agent_mode || 'build',
                llm_config_id: this.form.value.llm_config ?? null,
                session_id: this.form.value.session_id || '',
                system_prompt: this.form.value.system_prompt || '',
                stream_handler_code: this.streamHandlerCode,
                libraries: librariesArray,
                polling_interval_ms: Number(this.form.value.polling_interval_ms) || 1000,
                silence_indicator_s: this.node().data.silence_indicator_s || 3,
                indicator_repeat_s: this.node().data.indicator_repeat_s || 5,
                chunk_timeout_s: Number(this.form.value.chunk_timeout_s) || 30,
                inactivity_timeout_s: Number(this.form.value.inactivity_timeout_s) || 120,
                max_wait_s: Number(this.form.value.max_wait_s) || 300,
                output_schema: this.parsedOutputSchema(),
            },
            stream_config: this.form.value.stream_config || {},
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

    private parsedOutputSchema(): Record<string, any> {
        if (!this.outputSchemaText.trim()) return {};
        try {
            return JSON.parse(this.outputSchemaText);
        } catch {
            return this.node().data.output_schema || {};
        }
    }
}
