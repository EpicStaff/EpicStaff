import { ChangeDetectionStrategy, Component, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormGroup, ReactiveFormsModule } from '@angular/forms';
import {
    ColumnResizeDividerComponent,
    createColumnWidthState,
    CustomInputComponent,
    ExecutionTimeoutFieldComponent,
    ExecutionTimeoutFormField,
    ValidationErrorsComponent,
} from '@shared/components';
import { ResourceCode, toSecretIds } from '@shared/models';
import { ExecutionTimeoutLimitsStorageService, SecretsStorageService } from '@shared/services';
import { merge, Subject } from 'rxjs';
import { debounceTime } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { PythonNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { PythonNode } from '../../../core/models/python-node.model';
import { NODE_PANEL_DIFF } from '../../../core/providers/node-panel-diff.token';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { mapFieldRowChanges } from '../../../utils/diff';
import { DiffFieldMarkComponent } from '../../diff-field-mark/diff-field-mark.component';
import { InputMapComponent } from '../../input-map/input-map.component';
import { NodeSecretsFieldComponent } from '../../node-secrets-field/node-secrets-field.component';
import { NodeStorageSectionComponent } from '../../node-storage-section/node-storage-section.component';
import {
    createInputMapFromPairs,
    getValidInputPairs,
    initializeInputMap,
    parseCommaSeparatedList,
} from '../node-panel-form.utils';
import { parseTestInputValues, PythonCodeTestRun } from '../shared/python-code-test-run/python-code-test-run';
import {
    NODE_SAVING_MESSAGE,
    pythonCodeSignature,
    resolveStoredCodeState,
    SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE,
    SAVE_NODE_BEFORE_CODE_RUN_MESSAGE,
    SAVE_TO_RUN_LATEST_CODE_MESSAGE,
    STORED_GRAPH_OUTDATED_MESSAGE,
    StoredCodeState,
} from '../shared/python-code-test-run/stored-python-code';
import {
    areValidParameterNames,
    diffNames,
    haveSameNames,
    namedKeys,
    parseMainParameters,
    planInputListChanges,
    rewriteMainParameters,
} from './python-main-signature.util';
import { PythonTerminalComponent } from './python-terminal/python-terminal.component';

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
        ExecutionTimeoutFieldComponent,
        DiffFieldMarkComponent,
    ],
    templateUrl: './python-node-panel.component.html',
    styleUrls: ['./python-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PythonNodePanelComponent extends BaseSidePanel<PythonNodeModel> {
    public readonly graphId = input<number | null>(null);
    private readonly inputMap = viewChild(InputMapComponent);
    public readonly isFormCollapsed = signal<boolean>(false);
    public readonly useStorage = signal<boolean>(false);
    protected readonly leftColumnWidth = createColumnWidthState('python-node', 406);
    /**
     * Changes tab of a version preview: what a restore does to each Input List row. The input map is diffed as
     * one value, so its keys are compared here. `null` anywhere else, so the list shows no row marks.
     */
    protected readonly inputMapRowChanges = computed(() => mapFieldRowChanges(this.panelDiff(), 'input_map'));

    /** Changing the selection needs Secrets:Use and an editable flow (not a Viewer, not a version preview). */
    public readonly canEditSecrets = computed(
        () => !this.isReadOnly() && this.permissionsService.canEditSecrets(ResourceCode.Flows)
    );
    public readonly secretsTooltip = computed(() =>
        this.canEditSecrets()
            ? "Secrets this Python code can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
            : this.isReadOnly()
              ? 'Secrets assigned to this Python code.'
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
    /** The Test mode run of the stored code and its terminal. */
    protected readonly codeTestRun = new PythonCodeTestRun();

    pythonCode: string = '';
    initialPythonCode: string = '';
    protected executionTimeout!: ExecutionTimeoutFormField;
    private initialFormSignatureExceptTestValues: string = '';
    private initialTestInputValuesSignature: string = '';
    codeEditorHasError: boolean = false;
    private readonly pythonCodeChange$ = new Subject<string>();
    /**
     * The signature and Input List names last seen in step: each side applies to the other only how its own
     * names moved away from these, so opening a node never syncs and an echo of a sync is a no-op.
     */
    private lastCodeParameterNames: string[] | null = null;
    private lastInputListNames: string[] = [];
    /** Set while a code edit rewrites the rows, so their change events do not rewrite the code back. */
    private isApplyingCodeToInputList = false;
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
    /** How the panel's code, libraries, secrets and storage flag relate to the ones the backend stores for the node. */
    private readonly storedCodeState = computed<StoredCodeState>(() =>
        resolveStoredCodeState(
            this.flowService.hasSavedGraph(),
            this.node().backendId,
            this.flowService.savedPythonNode(this.node().backendId),
            (savedNode) => this.differsFromSaved(savedNode)
        )
    );
    /**
     * Why the test Run cannot run now, or null. The backend runs the code and storage flag it stores for the
     * node, not the panel's: an edit (e.g. toggling storage, whose autosave only reaches the flow) must be
     * saved first, or the run would use the old one. A run in flight is reported by the input map itself.
     */
    protected readonly runTestBlocker = computed<string | null>(() => {
        if (this.isSaving()) return NODE_SAVING_MESSAGE;
        switch (this.storedCodeState()) {
            case 'outdated':
                return STORED_GRAPH_OUTDATED_MESSAGE;
            case 'not-created':
                return SAVE_NODE_BEFORE_CODE_RUN_MESSAGE;
            case 'missing':
                return SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE;
            case 'changed':
                return SAVE_TO_RUN_LATEST_CODE_MESSAGE;
            case 'stored':
                return null;
        }
    });
    /**
     * The node must be saved before its test can run although the panel may have no edit (a new node, or one
     * reopened after an edit that only reached the flow): the panel shell then shows its Save button too.
     * Save cannot help a `missing` or `outdated` node.
     */
    public readonly needsSave = computed(() => {
        if (this.isReadOnly()) return false;
        const state = this.storedCodeState();
        return state === 'not-created' || state === 'changed';
    });

    private readonly sidePanelService = inject(SidePanelService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly panelDiff = inject(NODE_PANEL_DIFF);
    private readonly permissionsService = inject(PermissionsService);
    private readonly flowService = inject(FlowService);
    private readonly executionTimeoutLimits = inject(ExecutionTimeoutLimitsStorageService);

    constructor() {
        super();
        this.pythonCodeChange$.pipe(debounceTime(300), takeUntilDestroyed()).subscribe(() => {
            this.syncInputListFromCode();
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
            use_storage: this.useStorage(),
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
            this.formDirtyTick.update((v) => v + 1);
        }
        this.sidePanelService.triggerAutosave();
    }

    removeStorageCode(code: string): void {
        const prefix = code + '\n\n';
        if (this.pythonCode.startsWith(prefix)) {
            this.pythonCode = this.pythonCode.slice(prefix.length);
            this.formDirtyTick.update((v) => v + 1);
            this.sidePanelService.triggerAutosave();
        }
    }

    initializeForm(): FormGroup {
        this.codeTestRun.reset();

        this.useStorage.set(this.node().data.use_storage ?? false);
        this.selectedSecretIds.set(this.node().data.secret_ids ?? []);

        this.executionTimeout = new ExecutionTimeoutFormField(
            this.node().data.execution_timeout,
            this.executionTimeoutLimits.limits()
        );
        const form = this.fb.group({
            node_name: [this.node().node_name, this.createNodeNameValidators()],
            input_map: this.fb.array([]),
            output_variable_path: [this.node().output_variable_path || ''],
            libraries: [this.node().data.libraries?.join(', ') || ''],
            execution_timeout: this.executionTimeout.control,
            test_input: this.fb.array([]),
        });

        this.initializeInputMap(form);
        this.initializeTestInput(form);

        this.pythonCode = this.node().data.code || '';
        this.initialPythonCode = this.pythonCode;
        this.form = form;
        this.initialFormSignatureExceptTestValues = this.buildFormSignatureExceptTestValues();
        this.initialTestInputValuesSignature = this.buildTestInputValuesSignature();
        // The values computed from the form (dirty state, stored-code state) were read without it.
        this.formDirtyTick.update((v) => v + 1);

        form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.formDirtyTick.update((v) => v + 1);
        });

        this.lastCodeParameterNames = parseMainParameters(this.pythonCode)?.names ?? null;
        this.lastInputListNames = namedKeys(this.inputMapPairs.getRawValue());
        merge(form.get('input_map')!.valueChanges, form.get('test_input')!.valueChanges)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.syncCodeFromInputList());

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
                execution_timeout: this.executionTimeout.value,
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

    /** The keys of the rows the user edits now: the test values in Test mode, the Input List otherwise. */
    private activeInputListNames(): string[] {
        return namedKeys(
            (this.form.get(this.isOpenTestMode() ? 'test_input' : 'input_map') as FormArray).getRawValue()
        );
    }

    private syncInputListFromCode(): void {
        const inputMap = this.inputMap();
        if (!this.form || !inputMap || this.isReadOnly()) return;
        const parameters = parseMainParameters(this.pythonCode);
        if (parameters === null || haveSameNames(parameters.names, this.lastCodeParameterNames)) return;
        const changes = planInputListChanges(this.lastCodeParameterNames, parameters);
        this.lastCodeParameterNames = parameters.names;

        this.isApplyingCodeToInputList = true;
        try {
            inputMap.applyKeyChanges(changes);
        } finally {
            this.isApplyingCodeToInputList = false;
        }
        this.lastInputListNames = this.activeInputListNames();
        this.formDirtyTick.update((v) => v + 1);
    }

    private syncCodeFromInputList(): void {
        if (this.isApplyingCodeToInputList || this.isReadOnly()) return;
        const names = this.activeInputListNames();
        // A key still being typed (not a name yet, or another row's) waits, keeping the last names to diff from.
        if (haveSameNames(names, this.lastInputListNames) || !areValidParameterNames(names)) return;
        // A signature edit whose debounced sync has not run yet wins; that sync takes the rows as they are then.
        const parameters = parseMainParameters(this.pythonCode);
        if (parameters !== null && !haveSameNames(parameters.names, this.lastCodeParameterNames)) return;

        const code = rewriteMainParameters(this.pythonCode, diffNames(this.lastInputListNames, names));
        this.lastInputListNames = names;
        if (code === null || code === this.pythonCode) return;
        this.lastCodeParameterNames = parseMainParameters(code)?.names ?? null;
        this.pythonCode = code;
        this.formDirtyTick.update((v) => v + 1);
        this.pythonCodeChange$.next(code);
    }

    onRunTest(variables: Record<string, string>): void {
        const backendId = this.node().backendId;
        if (this.runTestBlocker() !== null || backendId == null) return;
        this.codeTestRun.run(
            {
                target: { type: 'python_node', id: backendId },
                variables: parseTestInputValues(variables),
            },
            this.executionTimeoutLimits.secondsToRun(
                this.flowService.savedPythonNode(backendId)?.python_code.execution_timeout
            )
        );
    }

    /** The code, libraries, secrets, storage flag or execution timeout in the panel are not the ones the backend stores. */
    private differsFromSaved(savedNode: PythonNode): boolean {
        this.formDirtyTick();
        if (!this.form) return true;
        const savedCode = savedNode.python_code;
        const saved = pythonCodeSignature(savedCode.code, savedCode.libraries, toSecretIds(savedCode.secrets));
        const current = pythonCodeSignature(
            this.pythonCode,
            parseCommaSeparatedList(this.form.value.libraries),
            this.selectedSecretIds()
        );
        return (
            saved !== current ||
            (savedNode.use_storage ?? false) !== this.useStorage() ||
            this.executionTimeoutLimits.secondsToRun(savedCode.execution_timeout) !==
                this.executionTimeoutLimits.secondsToRun(this.executionTimeout.value)
        );
    }
}
