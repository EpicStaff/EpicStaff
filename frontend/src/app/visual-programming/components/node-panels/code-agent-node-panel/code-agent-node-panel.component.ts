import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { expandCollapseAnimation } from '@shared/animations';
import { CustomInputComponent, JsonEditorComponent } from '@shared/components';
import { FullLLMConfig, FullLLMConfigService } from '@shared/services';
import { Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { CodeAgentNodeModel } from '../../../core/models/node.model';
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
import { DEFAULT_OUTPUT_SCHEMA } from './default-output-schema';

@Component({
    standalone: true,
    selector: 'app-code-agent-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        NodeStorageSectionComponent,
        CodeEditorComponent,
        CommonModule,
        JsonEditorComponent,
        CustomInputComponent,
        JsonEditorComponent,
    ],
    animations: [expandCollapseAnimation],
    templateUrl: './code-agent-node-panel.component.html',
    styleUrls: ['./code-agent-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CodeAgentNodePanelComponent extends BaseSidePanel<CodeAgentNodeModel> {
    public override readonly isExpanded = input<boolean>(false);
    public readonly isCodeEditorFullWidth = signal<boolean>(true);
    public readonly activeEditorTab = signal<'hooks' | 'schema'>('hooks');
    public readonly useStorage = signal<boolean>(false);

    streamHandlerCode: string = '';
    outputSchemaText: string = '';
    outputSchemaError: string = '';
    codeEditorHasError: boolean = false;
    llmConfigs: FullLLMConfig[] = [];
    private readonly codeChange$ = new Subject<string>();

    constructor(
        private readonly sidePanelService: SidePanelService,
        private readonly fullLLMConfigService: FullLLMConfigService,
        private readonly cdr: ChangeDetectorRef
    ) {
        super();
        this.codeChange$.pipe(debounceTime(300), takeUntilDestroyed()).subscribe(() => {
            this.sidePanelService.triggerAutosave();
        });
        this.fullLLMConfigService
            .getFullLLMConfigs()
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

    onStorageToggle(value: boolean): void {
        this.useStorage.set(value);
        this.sidePanelService.triggerAutosave();
    }

    insertStorageCode(code: string): void {
        if (!this.streamHandlerCode.includes('epicstaff_storage')) {
            this.streamHandlerCode = code + '\n\n' + this.streamHandlerCode;
        }
        this.sidePanelService.triggerAutosave();
    }

    removeStorageCode(code: string): void {
        const prefix = code + '\n\n';
        if (this.streamHandlerCode.startsWith(prefix)) {
            this.streamHandlerCode = this.streamHandlerCode.slice(prefix.length);
            this.sidePanelService.triggerAutosave();
        }
    }

    initializeForm(): FormGroup {
        const data = this.node().data;

        this.useStorage.set(data.use_storage ?? false);

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
        this.outputSchemaText =
            schema && Object.keys(schema).length > 0
                ? JSON.stringify(schema, null, 2)
                : JSON.stringify(DEFAULT_OUTPUT_SCHEMA, null, 2);

        return form;
    }

    createUpdatedNode(): CodeAgentNodeModel {
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

    private parsedOutputSchema(): Record<string, unknown> {
        if (!this.outputSchemaText.trim()) return {};
        try {
            return JSON.parse(this.outputSchemaText);
        } catch {
            return this.node().data.output_schema || {};
        }
    }
}
