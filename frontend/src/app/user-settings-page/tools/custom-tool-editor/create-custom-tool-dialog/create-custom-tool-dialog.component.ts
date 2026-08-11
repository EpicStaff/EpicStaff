import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import type { editor as MonacoEditor } from 'monaco-editor';
import { EMPTY } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import {
    CreatePythonCodeToolPayload,
    GetPythonCodeToolRequest,
} from '../../../../features/tools/models/python-code-tool.model';
import { CustomToolsService } from '../../../../features/tools/services/custom-tools/custom-tools.service';
import { ToolsEventsService } from '../../../../features/tools/services/tools-events.service';
import { ToastService } from '../../../../services/notifications';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { ChipsInputComponent } from '../../../../shared/components/chips-input/chips-input.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { ToggleSwitchComponent } from '../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { JsonEditorComponent, JsonError } from '../../../../shared/components/json-editor/json-editor.component';
import { TextareaComponent } from '../../../../shared/components/textarea/textarea.component';
import { CodeEditorComponent } from '../code-editor/code-editor.component';
import {
    DrillStep,
    ParametersTableViewComponent,
} from './components/parameters-table-view/parameters-table-view.component';
import { DEFAULT_ENTRYPOINT, toCreatePayload } from './models/create-custom-tool-form.model';
import { parseToolVariablesJson, serializeVariables, ToolVariable } from './parameters';
import {
    isToolJsonSchemaValid,
    objectDefaultDataMarkers,
    TOOL_VARIABLES_JSON_SCHEMA,
} from './schema/tool-variables-schema';

enum ActiveEditor {
    None = 'none',
    Python = 'python',
    Json = 'json',
}

interface CreateCustomToolDialogData {
    pythonTools?: GetPythonCodeToolRequest[];
    selectedTool?: GetPythonCodeToolRequest;
}

/** `fork` is the built-in path: a POST that leaves the immutable original alone. */
type SaveAction = 'create' | 'update' | 'fork';

/** A fork is announced by {@link CreateCustomToolDialogComponent.adoptForkedCopy} instead, which names the copy. */
const SAVE_SUCCESS_MESSAGES: Record<Exclude<SaveAction, 'fork'>, string> = {
    create: 'Custom tool created successfully!',
    update: 'Custom tool updated successfully!',
};

const SAVE_FAILURE_MESSAGES: Record<SaveAction, string> = {
    create: 'Failed to create custom tool. Please try again.',
    update: 'Failed to update custom tool. Please try again.',
    fork: 'Failed to save your copy of this built-in tool. Please try again.',
};

const DEFAULT_PYTHON_CODE = `def main() -> dict:
    return {"status": "ok"}
`;

/** Explains why the built-in header button offers "Create Editable Copy" instead of editing in place. */
const BUILT_IN_SAVE_TOOLTIP =
    'Built-in tools are read-only. Create an editable copy to make changes; the original stays untouched.';

const VARIABLES_SCHEMA_TOOLTIP =
    'Variables must be a JSON array. Each item defines one parameter: name, type, description, input_type, required, and default_value. input_type can be agent_input (agent supplies it), user_input (configured/default value, hidden from the agent), or mixed (agent may override configured/default value).';

@Component({
    selector: 'app-create-custom-tool-dialog',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        MatTooltipModule,
        AppSvgIconComponent,
        ButtonComponent,
        ChipsInputComponent,
        CustomInputComponent,
        HelpTooltipComponent,
        CodeEditorComponent,
        JsonEditorComponent,
        TextareaComponent,
        ToggleSwitchComponent,
        ParametersTableViewComponent,
        HasPermissionDirective,
    ],
    templateUrl: './create-custom-tool-dialog.component.html',
    styleUrls: ['./create-custom-tool-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateCustomToolDialogComponent {
    private readonly fb = inject(NonNullableFormBuilder);
    private readonly dialogRef = inject<DialogRef<GetPythonCodeToolRequest>>(DialogRef);
    private readonly destroyRef = inject(DestroyRef);
    private readonly customToolsService = inject(CustomToolsService);
    private readonly toast = inject(ToastService);
    private readonly confirmDialog = inject(ConfirmationDialogService);
    private readonly toolsEvents = inject(ToolsEventsService);
    private readonly dialogData = inject<CreateCustomToolDialogData | null>(DIALOG_DATA, { optional: true });

    /** Rebound to the forked copy once a built-in tool is saved, so later saves update that copy. */
    public readonly selectedTool = signal<GetPythonCodeToolRequest | null>(this.dialogData?.selectedTool ?? null);
    public readonly isEditMode = computed(() => this.selectedTool() !== null);
    public readonly isBuiltIn = computed(() => this.selectedTool()?.built_in === true);
    public readonly dialogTitle = computed(() => {
        if (this.isBuiltIn()) {
            return 'Built-in Tool';
        }
        return this.isEditMode() ? 'Edit Custom Tool' : 'Create Custom Tool';
    });

    private readonly baseJsonEditorOptions: MonacoEditor.IStandaloneEditorConstructionOptions = {
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        formatOnPaste: true,
        formatOnType: true,
        tabSize: 2,
    };

    public readonly jsonEditorOptions = computed<MonacoEditor.IStandaloneEditorConstructionOptions>(() => ({
        ...this.baseJsonEditorOptions,
        readOnly: this.isBuiltIn(),
    }));

    public readonly form = this.fb.group({
        name: this.fb.control(this.selectedTool()?.name ?? '', [Validators.required]),
        description: this.fb.control(this.selectedTool()?.description ?? '', [Validators.required]),
        pythonCode: this.fb.control(this.selectedTool()?.python_code?.code ?? DEFAULT_PYTHON_CODE, [
            Validators.required,
        ]),
        variablesJson: this.fb.control(this.initialVariablesJson(), [Validators.required]),
        libraries: this.fb.control<string[]>(this.selectedTool()?.python_code?.libraries ?? []),
    });

    public readonly ActiveEditor = ActiveEditor;
    public readonly variablesSchemaTooltip = VARIABLES_SCHEMA_TOOLTIP;
    public readonly builtInSaveTooltip = BUILT_IN_SAVE_TOOLTIP;

    private readonly parametersTableView = viewChild(ParametersTableViewComponent);

    public readonly tableVariables = signal<ToolVariable[]>([]);
    public readonly tableDrillStack = signal<DrillStep[]>([]);

    public readonly activeEditor = signal<ActiveEditor>(ActiveEditor.Python);
    public readonly pythonSectionExpanded = signal(false);
    public readonly jsonSectionExpanded = signal(false);
    public readonly parametersTableMode = signal(true);
    public readonly isJsonValid = signal(true);
    public readonly jsonIssues = signal<JsonError[]>([]);
    public readonly lastValidJson = signal('');
    public readonly toolVariablesSchema = TOOL_VARIABLES_JSON_SCHEMA;
    public readonly objectDefaultMarkers = objectDefaultDataMarkers;
    public readonly pythonHasError = signal(false);
    public readonly isSaving = signal(false);
    public readonly isCopying = signal(false);
    private tableImportWasInvalid = false;

    private initialSnapshot = '';

    private monacoJsonEditor: MonacoEditor.IStandaloneCodeEditor | null = null;

    constructor() {
        effect(() => {
            const active = this.activeEditor();
            if (active === ActiveEditor.Json) {
                queueMicrotask(() => this.monacoJsonEditor?.layout());
            }
        });

        const parsedDefault = parseToolVariablesJson(this.form.controls.variablesJson.value);
        this.tableVariables.set(parsedDefault.valid ? parsedDefault.variables : []);

        this.initialSnapshot = this.computeSnapshot();
        const initialJson = this.form.controls.variablesJson.value;
        if (isToolJsonSchemaValid(initialJson)) {
            this.lastValidJson.set(initialJson);
        }

        this.dialogRef.disableClose = true;
        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.requestClose());
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                this.requestClose();
            }
        });
    }

    public toggleEditor(target: ActiveEditor.Python | ActiveEditor.Json): void {
        const next = this.activeEditor() === target ? ActiveEditor.None : target;
        this.activeEditor.set(next);
        if (next === ActiveEditor.Python) {
            this.pythonSectionExpanded.set(false);
        }
        if (next === ActiveEditor.Json) {
            this.jsonSectionExpanded.set(false);
        }
    }

    public isEditorActive(target: ActiveEditor.Python | ActiveEditor.Json): boolean {
        return this.activeEditor() === target;
    }

    public togglePythonSection(): void {
        const expanded = !this.pythonSectionExpanded();
        this.pythonSectionExpanded.set(expanded);
        if (expanded && this.activeEditor() === ActiveEditor.Python) {
            this.activeEditor.set(ActiveEditor.None);
        }
    }

    public toggleJsonSection(): void {
        const expanded = !this.jsonSectionExpanded();
        this.jsonSectionExpanded.set(expanded);
        if (expanded && this.activeEditor() === ActiveEditor.Json) {
            this.activeEditor.set(ActiveEditor.None);
        }
    }

    public setParametersTableMode(enabled: boolean): void {
        if (this.parametersTableMode() === enabled) {
            return;
        }

        if (enabled) {
            const value = this.form.controls.variablesJson.value;
            if (!isToolJsonSchemaValid(value)) {
                this.confirmDialog
                    .confirm({
                        title: 'Invalid Code Detected',
                        message: 'The code contains errors and cannot be validated.',
                        caution:
                            'If you switch to table mode now, your <strong>progress will be lost</strong> and the <strong>table will be empty</strong>.',
                        confirmText: 'Stay and Fix',
                        cancelText: 'Switch Anyway',
                        type: 'warning',
                    })
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe((result) => {
                        if (result === false) {
                            this.applyEnableTableMode([]);
                            this.tableImportWasInvalid = true;
                        }
                    });
                return;
            }

            this.applyEnableTableMode(parseToolVariablesJson(value).variables);
            this.tableImportWasInvalid = false;
            return;
        }

        const tableView = this.parametersTableView();
        if (tableView && !tableView.isValid()) {
            tableView.validate();
            this.confirmDialog
                .confirm({
                    title: 'Incomplete Fields',
                    message: 'Some fields have errors and cannot be fully represented in JSON.',
                    caution: 'If you switch to JSON now, incomplete fields may be <strong>dropped</strong>.',
                    confirmText: 'Stay and Fix',
                    cancelText: 'Switch Anyway',
                    type: 'warning',
                })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((result) => {
                    if (result === false) {
                        this.applyDisableTableMode();
                    }
                });
            return;
        }

        this.applyDisableTableMode();
    }

    private applyDisableTableMode(): void {
        this.parametersTableMode.set(false);
        this.form.controls.variablesJson.setValue(JSON.stringify(serializeVariables(this.tableVariables()), null, 2));
        this.form.controls.variablesJson.markAsDirty();
        this.isJsonValid.set(true);
        this.tableImportWasInvalid = false;
        this.jsonSectionExpanded.set(true);
        const serialized = this.form.controls.variablesJson.value;
        if (isToolJsonSchemaValid(serialized)) {
            this.lastValidJson.set(serialized);
        }
    }

    private applyEnableTableMode(variables: ToolVariable[]): void {
        this.tableVariables.set(variables);
        this.parametersTableMode.set(true);
        this.jsonSectionExpanded.set(false);
        this.jsonIssues.set([]);
        if (this.activeEditor() === ActiveEditor.Json) {
            this.activeEditor.set(ActiveEditor.Python);
        }
    }

    public copyPythonCode(): void {
        this.copyToClipboard(this.form.controls.pythonCode.value, 'Python code copied');
    }

    public copyJsonConfiguration(): void {
        this.copyToClipboard(this.form.controls.variablesJson.value, 'JSON configuration copied');
    }

    public onJsonChange(json: string): void {
        this.form.controls.variablesJson.setValue(json);
        this.form.controls.variablesJson.markAsDirty();
        if (isToolJsonSchemaValid(json)) {
            this.lastValidJson.set(json);
        }
    }

    public onJsonValidationChange(isValid: boolean): void {
        this.isJsonValid.set(isValid);
    }

    public onJsonErrorsChange(errors: JsonError[]): void {
        this.jsonIssues.set(errors);
    }

    public revertToLastValidJson(): void {
        const snapshot = this.lastValidJson();
        if (!snapshot) {
            return;
        }
        this.form.controls.variablesJson.setValue(snapshot);
        this.form.controls.variablesJson.markAsDirty();
        this.jsonIssues.set([]);
        this.isJsonValid.set(true);
    }

    public onJsonEditorReady(editor: MonacoEditor.IStandaloneCodeEditor): void {
        this.monacoJsonEditor = editor;
    }

    public onPythonCodeChange(code: string): void {
        this.form.controls.pythonCode.setValue(code);
        this.form.controls.pythonCode.markAsDirty();
    }

    public onPythonErrorChange(hasError: boolean): void {
        this.pythonHasError.set(hasError);
    }

    public onVariablesChange(vars: ToolVariable[]): void {
        this.tableVariables.set(vars);
        this.form.controls.variablesJson.markAsDirty();
    }

    public onDrillStackChange(stack: DrillStep[]): void {
        this.tableDrillStack.set(stack);
    }

    public closeEditorPane(): void {
        this.activeEditor.set(ActiveEditor.None);
    }

    public close(): void {
        this.requestClose();
    }

    private requestClose(): void {
        if (this.isSaving()) {
            return;
        }
        if (this.computeSnapshot() === this.initialSnapshot) {
            this.dialogRef.close();
            return;
        }

        this.confirmDialog
            .confirm({
                title: 'Leave without saving?',
                message: 'You have unsaved changes in this tool.',
                cautionTitle: 'Attention',
                caution: 'If you leave now, your <strong>changes will be lost</strong>.',
                confirmText: 'Leave',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.dialogRef.close();
                }
            });
    }

    public makeCopy(): void {
        const original = this.selectedTool();
        if (!original || this.isCopying()) {
            return;
        }

        const variables = Array.isArray(original.variables) ? original.variables : [];
        const payload: CreatePythonCodeToolPayload = {
            name: this.uniqueToolName(original.name.trim()),
            description: original.description,
            variables,
            use_storage: original.use_storage ?? false,
            python_code: {
                code: original.python_code?.code ?? '',
                entrypoint: original.python_code?.entrypoint?.trim() || DEFAULT_ENTRYPOINT,
                libraries: original.python_code?.libraries ?? [],
                global_kwargs: {},
            },
        };

        this.isCopying.set(true);
        this.customToolsService
            .createPythonCodeToolV2(payload)
            .pipe(
                tap((created) => {
                    this.toolsEvents.emitCustomToolCreated(created);
                    this.toast.success(`Tool copied as "${created.name}"`);
                }),
                catchError((err: HttpErrorResponse) => {
                    console.error('Error copying tool:', err);
                    this.toast.error(this.nameConflictMessage(err) ?? 'Failed to copy custom tool. Please try again.');
                    return EMPTY;
                }),
                finalize(() => this.isCopying.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private copyToClipboard(value: string, successMessage: string): void {
        navigator.clipboard
            .writeText(value)
            .then(() => this.toast.success(successMessage))
            .catch(() => this.toast.error('Failed to copy to clipboard'));
    }

    public submit(): void {
        if (this.isSaving()) {
            return;
        }

        if (this.parametersTableMode()) {
            this.parametersTableView()?.validate();
            this.form.controls.variablesJson.setValue(
                JSON.stringify(serializeVariables(this.tableVariables()), null, 2)
            );
            this.form.controls.variablesJson.markAsDirty();
            this.isJsonValid.set(true);
            this.tableImportWasInvalid = false;
        }

        this.form.markAllAsTouched();

        const error = this.getValidationError();
        if (error) {
            this.toast.warning(error);
            return;
        }

        let payload: CreatePythonCodeToolPayload;
        try {
            payload = this.buildPayload();
        } catch {
            this.toast.error('Failed to parse JSON Configuration');
            return;
        }

        const editingTool = this.selectedTool();
        const action: SaveAction = editingTool === null ? 'create' : editingTool.built_in ? 'fork' : 'update';
        if (editingTool?.built_in) {
            payload = { ...payload, name: this.forkName(payload.name, editingTool.name) };
        }

        this.isSaving.set(true);

        const request$ =
            editingTool && !editingTool.built_in
                ? this.customToolsService.updatePythonCodeToolV2(editingTool.id, payload)
                : this.customToolsService.createPythonCodeToolV2(payload);

        request$
            .pipe(
                tap((result) => {
                    if (action === 'fork') {
                        this.adoptForkedCopy(result);
                        return;
                    }
                    this.toast.success(SAVE_SUCCESS_MESSAGES[action]);
                    this.dialogRef.close(result);
                }),
                catchError((err: HttpErrorResponse) => {
                    console.error(`Error on tool ${action}:`, err);
                    this.toast.error(this.nameConflictMessage(err) ?? SAVE_FAILURE_MESSAGES[action]);
                    return EMPTY;
                }),
                finalize(() => this.isSaving.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private nameConflictMessage(err: HttpErrorResponse): string | null {
        if (err.status !== 400) {
            return null;
        }
        const body = err.error as { name?: string[] } | null;
        const message = body?.name?.[0];
        return typeof message === 'string' ? message : null;
    }

    private adoptForkedCopy(created: GetPythonCodeToolRequest): void {
        this.selectedTool.set(created);
        this.form.controls.name.setValue(created.name);
        this.form.markAsPristine();
        this.initialSnapshot = this.computeSnapshot();
        this.toolsEvents.emitCustomToolCreated(created);
        this.toast.success(`Editable copy "${created.name}" created`);
    }

    private forkName(desiredName: string, builtInName: string): string {
        return desiredName === builtInName.trim() ? this.uniqueToolName(desiredName) : desiredName;
    }

    private uniqueToolName(base: string): string {
        const taken = new Set((this.dialogData?.pythonTools ?? []).map((tool) => tool.name.trim()));
        let candidate = `${base} (copy)`;
        for (let n = 2; taken.has(candidate); n++) {
            candidate = `${base} (copy ${n})`;
        }
        return candidate;
    }

    private computeSnapshot(): string {
        const { name, description, pythonCode, libraries } = this.form.getRawValue();
        return JSON.stringify({
            name,
            description,
            pythonCode,
            libraries: [...libraries].sort(),
            variables: this.snapshotVariables(),
        });
    }

    private snapshotVariables(): string {
        if (this.parametersTableMode()) {
            return JSON.stringify(serializeVariables(this.tableVariables()));
        }
        const parsed = parseToolVariablesJson(this.form.controls.variablesJson.value);
        return parsed.valid
            ? JSON.stringify(serializeVariables(parsed.variables))
            : `invalid:${this.form.controls.variablesJson.value.trim()}`;
    }

    private initialVariablesJson(): string {
        const variables = this.selectedTool()?.variables;
        return JSON.stringify(Array.isArray(variables) ? variables : [], null, 2);
    }

    private getValidationError(): string | null {
        if (this.form.invalid) {
            return 'Please fill in all required fields';
        }
        if (this.parametersTableMode() && !(this.parametersTableView()?.isValid() ?? true)) {
            return 'Please fix the parameter errors before saving';
        }
        if (!this.isJsonValid()) {
            return 'JSON Configuration is invalid';
        }
        if (this.pythonHasError()) {
            return 'Fix Python syntax errors before saving';
        }
        return null;
    }

    private buildPayload(): CreatePythonCodeToolPayload {
        const source = this.selectedTool();
        return toCreatePayload(this.form.getRawValue(), {
            entrypoint: source?.python_code?.entrypoint,
            useStorage: source?.use_storage,
        });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
