import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { Subject, switchMap } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { PythonNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import {
    PollEvent,
    PythonCodeResult,
    PythonCodeRunService,
    RunPythonCodeRequest,
} from '../../../services/python-code-run.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { InputMapComponent } from '../../input-map/input-map.component';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';
import { NodeStorageSectionComponent } from '../../node-storage-section/node-storage-section.component';
import {
    createInputMapFromPairs,
    getValidInputPairs,
    initializeInputMap,
    parseCommaSeparatedList,
} from '../node-panel-form.utils';
import { PythonTerminalComponent, TerminalStatus } from './python-terminal/python-terminal.component';
import { TerminalLogEntry, TerminalLogType } from './python-terminal/terminal-log.model';

@Component({
    selector: 'app-python-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        InputMapComponent,
        CodeEditorComponent,
        PythonTerminalComponent,
        NodeStorageSectionComponent,
        NodeSecretsFieldComponent,
        ColumnResizeDividerComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './python-node-panel.component.html',
    styleUrls: ['./python-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PythonNodePanelComponent extends BaseSidePanel<PythonNodeModel> {
    public readonly graphId = input<number | null>(null);
    public readonly isFormCollapsed = signal<boolean>(false);
    public readonly useStorage = signal<boolean>(false);
    protected readonly leftColumnWidth = createColumnWidthState('python-node', 406);

    public readonly canEditSecrets = computed(() => this.permissionsService.canEditSecrets(ResourceCode.Flows));
    public readonly secretsTooltip = computed(() =>
        this.canEditSecrets()
            ? "Secrets this Python code can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
            : "Secrets already assigned to this Python code. You don't have permission to change which secrets are selected."
    );
    public readonly selectedSecretIds = signal<number[]>([]);
    public readonly secretNames = computed(() =>
        this.canEditSecrets()
            ? this.secretsStorageService.namesForIds(this.selectedSecretIds())
            : (this.node().data.secret_names ?? [])
    );
    public readonly inputMapKeys = computed(() => {
        this.formDirtyTick();
        if (!this.form) return [];
        return getValidInputPairs(this.inputMapPairs)
            .map((control) => (control.value.key as string)?.trim())
            .filter((key): key is string => !!key);
    });

    isOpenTestMode = signal(false);
    testResult = signal<PythonCodeResult | null>(null);
    testError = signal<string | null>(null);
    testRunning = signal(false);
    terminalLogs = signal<TerminalLogEntry[]>([]);
    terminalHeight = signal<number>(150);

    terminalStatus = computed<TerminalStatus>(() => {
        if (this.testRunning()) return 'processing';
        if (this.testError()) return 'error';
        const r = this.testResult();
        if (r) return r.status === 'completed' ? 'done' : 'error';
        return 'idle';
    });

    pythonCode: string = '';
    initialPythonCode: string = '';
    private initialFormSignatureExceptTestValues: string = '';
    private initialTestInputValuesSignature: string = '';
    codeEditorHasError: boolean = false;
    private readonly pythonCodeChange$ = new Subject<string>();
    private readonly formDirtyTick = signal(0);
    public readonly testInputDirty = computed(() => {
        this.formDirtyTick();
        if (!this.form) return false;
        return this.buildTestInputValuesSignature() !== this.initialTestInputValuesSignature;
    });

    public override readonly isDirty = computed(() => {
        this.formDirtyTick();
        if (!this.form) return false;
        return (
            this.buildFormSignatureExceptTestValues() !== this.initialFormSignatureExceptTestValues ||
            this.pythonCode !== this.initialPythonCode ||
            this.buildTestInputValuesSignature() !== this.initialTestInputValuesSignature
        );
    });
    public readonly isSaving = computed(() => this.sidePanelService.savingNodeId() === this.node().id);
    private wasSaving = false;

    constructor(
        private readonly sidePanelService: SidePanelService,
        private readonly pythonCodeRunService: PythonCodeRunService,
        private readonly secretsStorageService: SecretsStorageService,
        private readonly permissionsService: PermissionsService
    ) {
        super();
        this.pythonCodeChange$.pipe(debounceTime(300), takeUntilDestroyed()).subscribe(() => {
            this.sidePanelService.triggerAutosave();
        });
        effect(() => {
            if (this.isOpenTestMode()) {
                this.sidePanelService.requestExpand();
            }
        });
        effect(() => {
            if (!this.isExpanded()) {
                this.isOpenTestMode.set(false);
            }
        });
        effect(() => {
            const saving = this.isSaving();
            if (this.wasSaving && !saving) {
                this.resetDirtyAfterSave();
            }
            this.wasSaving = saving;
        });
        this.sidePanelService.graphSaved$.pipe(takeUntilDestroyed()).subscribe(() => this.resetDirtyAfterGraphSave());
    }

    private resetDirtyAfterSave(): void {
        if (!this.form) return;
        this.form.markAsPristine();
        this.initialPythonCode = this.pythonCode;
        this.initialFormSignatureExceptTestValues = this.buildFormSignatureExceptTestValues();
        this.initialTestInputValuesSignature = this.buildTestInputValuesSignature();
        this.formDirtyTick.update((v) => v + 1);
    }

    private resetDirtyAfterGraphSave(): void {
        if (!this.form) return;
        this.initialPythonCode = this.pythonCode;
        this.initialFormSignatureExceptTestValues = this.buildFormSignatureExceptTestValues();
        this.formDirtyTick.update((v) => v + 1);
    }

    private buildFormSignatureExceptTestValues(): string {
        const raw = this.form.getRawValue() as Record<string, unknown>;
        const testInput = (raw['test_input'] as { key: string; value: string }[] | undefined) ?? [];
        const stripped = {
            ...raw,
            test_input: testInput.map((p) => ({ key: p.key, value: '' })),
            secret_ids: [...this.selectedSecretIds()].sort(),
        };
        return JSON.stringify(stripped);
    }

    private buildTestInputValuesSignature(): string {
        return JSON.stringify(this.getTestInputValue());
    }

    get activeColor(): string {
        return 'var(--accent-color)';
    }

    get inputMapPairs(): FormArray {
        return this.form.get('input_map') as FormArray;
    }

    onPythonCodeChange(code: string): void {
        this.pythonCode = code;
        this.pythonCodeChange$.next(code);
        this.formDirtyTick.update((v) => v + 1);
    }

    onSaveClick(): void {
        if (!this.form || this.form.invalid || this.isSaving()) return;
        const updatedNode = this.createUpdatedNode({ manualSave: true });
        this.sidePanelService.requestSaveNode(updatedNode);
    }

    onCodeErrorChange(hasError: boolean): void {
        this.codeEditorHasError = hasError;
    }

    onSecretsChange(values: number[]): void {
        this.selectedSecretIds.set(values);
        this.formDirtyTick.update((v) => v + 1);
        this.sidePanelService.triggerAutosave();
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
        this.terminalLogs.set([]);

        this.useStorage.set(this.node().data.use_storage ?? false);
        this.selectedSecretIds.set(this.node().data.secret_ids ?? []);

        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            libraries: [this.node().data.libraries?.join(', ') || ''],
            test_input: this.fb.array([]),
        });

        this.initializeInputMap(form);
        this.initializeTestInput(form);

        this.pythonCode = this.node().data.code || '';
        this.initialPythonCode = this.pythonCode;
        this.form = form;
        this.initialFormSignatureExceptTestValues = this.buildFormSignatureExceptTestValues();
        this.initialTestInputValuesSignature = this.buildTestInputValuesSignature();

        form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.formDirtyTick.update((v) => v + 1);
        });

        return form;
    }

    createUpdatedNode(opts?: { manualSave?: boolean }): PythonNodeModel {
        const validInputPairs = getValidInputPairs(this.inputMapPairs);
        const inputMapValue = createInputMapFromPairs(validInputPairs);
        if (this.isOpenTestMode()) {
            const testArray = this.form.get('test_input') as FormArray;
            const testKeys = new Set(
                testArray.controls.map((c) => (c.value.key as string)?.trim()).filter((k): k is string => !!k)
            );
            for (const key of Object.keys(inputMapValue)) {
                if (!testKeys.has(key)) {
                    delete inputMapValue[key];
                }
            }
            for (const key of testKeys) {
                if (!(key in inputMapValue)) {
                    inputMapValue[key] = 'variables.';
                }
            }
        }
        const librariesArray = parseCommaSeparatedList(this.form.value.libraries);

        return {
            ...this.node(),
            node_name: this.form.value.node_name,
            input_map: inputMapValue,
            output_variable_path: this.form.value.output_variable_path || null,
            data: {
                ...this.node().data,
                name: this.form.value.node_name || 'Python Code',
                code: this.pythonCode,
                entrypoint: 'main',
                libraries: librariesArray,
                use_storage: this.useStorage(),
                secret_ids: this.selectedSecretIds(),
                secret_names: this.secretNames(),
            },
            test_input: opts?.manualSave ? this.getTestInputValue() : this.getTestInputValuePreservingSaved(),
        };
    }

    private getTestInputValue(): Record<string, string> {
        const testArray = this.form.get('test_input') as FormArray;
        return testArray.controls.reduce((acc: Record<string, string>, c) => {
            const key = (c.value.key as string)?.trim();
            if (key) {
                acc[key] = (c.value.value as string) ?? '';
            }
            return acc;
        }, {});
    }

    private getTestInputValuePreservingSaved(): Record<string, string> {
        const testArray = this.form.get('test_input') as FormArray;
        const previouslySaved = (this.node().test_input ?? {}) as Record<string, string>;
        return testArray.controls.reduce((acc: Record<string, string>, c) => {
            const key = (c.value.key as string)?.trim();
            if (key) {
                const currentFormValue = (c.value.value as string) ?? '';
                acc[key] = previouslySaved[key] ?? currentFormValue;
            }
            return acc;
        }, {});
    }

    private initializeTestInput(form: FormGroup): void {
        const testArray = form.get('test_input') as FormArray;
        const data = this.node().test_input;
        if (data && typeof data === 'object') {
            Object.entries(data).forEach(([key, value]) => {
                testArray.push(
                    this.fb.group({
                        key: [key],
                        value: [String(value ?? '')],
                    })
                );
            });
        }
    }

    private initializeInputMap(form: FormGroup): void {
        initializeInputMap(form, this.node().input_map as Record<string, unknown> | null | undefined, this.fb);
    }

    onTerminalHeightChange(height: number): void {
        this.terminalHeight.set(height);
    }

    onClearLogs(): void {
        this.terminalLogs.set([]);
    }

    private addLog(type: TerminalLogType, message: string): void {
        this.terminalLogs.update((logs) => [...logs, { timestamp: new Date(), type, message }]);
    }

    private parseVariableValue(raw: string): unknown {
        try {
            return JSON.parse(raw);
        } catch {
            return raw;
        }
    }

    onRunTest(variables: Record<string, string>): void {
        this.testRunning.set(true);
        this.testResult.set(null);
        this.testError.set(null);
        this.terminalLogs.set([]);

        this.addLog('info', 'Starting function main()...');

        const libraries = this.form.value.libraries
            ? this.form.value.libraries
                  .split(',')
                  .map((lib: string) => lib.trim())
                  .filter((lib: string) => lib.length > 0)
            : [];

        const parsedVariables = Object.fromEntries(
            Object.entries(variables).map(([k, v]) => [k, this.parseVariableValue(v)])
        );

        const payload: RunPythonCodeRequest = {
            python_code_id: this.node().python_code_id ?? null,
            code: this.pythonCode,
            entrypoint: 'main',
            libraries,
            variables: parsedVariables,
        };

        this.addLog('info', `Parameters: ${JSON.stringify(parsedVariables)}`);

        this.pythonCodeRunService
            .runPythonCode(payload)
            .pipe(
                switchMap(({ execution_id }) => this.pythonCodeRunService.pollResultWithEvents(execution_id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (event: PollEvent) => {
                    if (event.type === 'polling') {
                        if (event.attempt === 1) {
                            this.addLog('polling', 'Processing...');
                        }
                    } else if (event.type === 'result') {
                        const result = event.data;
                        this.testResult.set(result);
                        this.testRunning.set(false);

                        if (result.stdout) {
                            this.addLog('stdout', result.stdout);
                        }
                        if (result.stderr) {
                            this.addLog('stderr', result.stderr);
                        }
                        if (result.status === 'completed') {
                            this.addLog('result', result.result_data || '(empty result)');
                        } else {
                            this.addLog('error', `Execution failed (return code: ${result.returncode})`);
                        }
                    }
                },
                error: (err: Error) => {
                    this.testError.set(err.message || 'Unknown error');
                    this.testRunning.set(false);
                    this.addLog('error', `Error: ${err.message || 'Unknown error'}`);
                },
            });
    }
}
