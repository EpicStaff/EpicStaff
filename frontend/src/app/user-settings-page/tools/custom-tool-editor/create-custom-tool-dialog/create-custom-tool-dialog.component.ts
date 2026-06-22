import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
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
import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';
import { TextareaComponent } from '../../../../shared/components/textarea/textarea.component';
import { CodeEditorComponent } from '../code-editor/code-editor.component';
import { parseToolVariablesJson, serializeVariables, ToolVariable } from './components/parameters-table.config';
import {
    DrillStep,
    ParametersTableViewComponent,
} from './components/parameters-table-view/parameters-table-view.component';
import { toCreatePayload } from './models/create-custom-tool-form.model';

enum ActiveEditor {
    None = 'none',
    Python = 'python',
    Json = 'json',
}

interface CreateCustomToolDialogData {
    pythonTools?: GetPythonCodeToolRequest[];
    selectedTool?: GetPythonCodeToolRequest;
}

const DEFAULT_PYTHON_CODE = `def main() -> dict:
    return {"status": "ok"}
`;

const DEFAULT_VARIABLES_JSON = `[
  {
    "name": "query",
    "type": "string",
    "description": "Search query provided by the agent",
    "input_type": "agent_input",
    "required": true,
    "default_value": null
  },
  {
    "name": "api_key",
    "type": "string",
    "description": "API key configured by the user",
    "input_type": "user_input",
    "required": true,
    "default_value": null
  },
  {
    "name": "max_results",
    "type": "number",
    "description": "Maximum number of results. Agent may override the default.",
    "input_type": "mixed",
    "required": false,
    "default_value": 10
  }
]`;

const VARIABLES_SCHEMA_TOOLTIP =
    'Variables must be a JSON array. Each item defines one parameter: name, type, description, input_type, required, and default_value. input_type can be agent_input (agent supplies it), user_input (configured/default value, hidden from the agent), or mixed (agent may override configured/default value).';

@Component({
    selector: 'app-create-custom-tool-dialog',
    imports: [
        CommonModule,
        ReactiveFormsModule,
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

    public readonly selectedTool: GetPythonCodeToolRequest | null = this.dialogData?.selectedTool ?? null;
    public readonly isEditMode = this.selectedTool !== null;

    public readonly form = this.fb.group({
        name: this.fb.control(this.selectedTool?.name ?? '', [Validators.required]),
        description: this.fb.control(this.selectedTool?.description ?? '', [Validators.required]),
        pythonCode: this.fb.control(this.selectedTool?.python_code?.code ?? DEFAULT_PYTHON_CODE, [Validators.required]),
        variablesJson: this.fb.control(
            this.selectedTool ? this.initialVariablesJsonFromTool(this.selectedTool) : DEFAULT_VARIABLES_JSON,
            [Validators.required]
        ),
        libraries: this.fb.control<string[]>(this.selectedTool?.python_code?.libraries ?? []),
    });

    public readonly ActiveEditor = ActiveEditor;
    public readonly variablesSchemaTooltip = VARIABLES_SCHEMA_TOOLTIP;

    private readonly parametersTableView = viewChild(ParametersTableViewComponent);

    public readonly tableVariables = signal<ToolVariable[]>([]);
    public readonly tableDrillStack = signal<DrillStep[]>([]);

    public readonly activeEditor = signal<ActiveEditor>(ActiveEditor.Python);
    public readonly pythonSectionExpanded = signal(false);
    public readonly jsonSectionExpanded = signal(false);
    public readonly parametersTableMode = signal(true);
    public readonly isJsonValid = signal(true);
    public readonly pythonHasError = signal(false);
    public readonly isSaving = signal(false);
    public readonly isCopying = signal(false);
    private tableImportWasInvalid = false;

    private monacoJsonEditor: MonacoEditor.IStandaloneCodeEditor | null = null;

    constructor() {
        // Re-layout the JSON Monaco editor whenever it becomes visible again.
        // Both editors set `automaticLayout: true`, but the very first measure
        // can be off when the right pane is animated/expanded - manually call
        // layout() on the next microtask to be safe.
        effect(() => {
            const active = this.activeEditor();
            if (active === ActiveEditor.Json) {
                queueMicrotask(() => this.monacoJsonEditor?.layout());
            }
        });

        const parsedDefault = parseToolVariablesJson(this.form.controls.variablesJson.value);
        this.tableVariables.set(parsedDefault.valid ? parsedDefault.variables : []);

        // Route backdrop click and Escape through the dirty-check guard.
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
        // Selecting a target for the right pane closes its inline preview to
        // avoid mounting two Monaco instances editing the same form control.
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
            const parsed = parseToolVariablesJson(this.form.controls.variablesJson.value);
            if (!parsed.valid) {
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
                        // result === false  → "Switch Anyway" (cancel button)
                        // result === true   → "Stay and Fix" (confirm button) → do nothing
                        // result === 'close'→ user dismissed → do nothing
                        if (result === false) {
                            this.applyEnableTableMode([]);
                            this.tableImportWasInvalid = true;
                        }
                    });
                return;
            }

            this.applyEnableTableMode(parsed.variables);
            this.tableImportWasInvalid = false;
            return;
        }

        this.parametersTableMode.set(false);
        this.form.controls.variablesJson.setValue(JSON.stringify(serializeVariables(this.tableVariables()), null, 2));
        this.form.controls.variablesJson.markAsDirty();
        this.isJsonValid.set(true);
        this.tableImportWasInvalid = false;
        this.jsonSectionExpanded.set(true);
    }

    private applyEnableTableMode(variables: ToolVariable[]): void {
        this.tableVariables.set(variables);
        this.parametersTableMode.set(true);
        this.jsonSectionExpanded.set(false);
        // If the JSON editor was occupying the right pane, swap it to Python
        // so the user keeps a useful editor visible instead of an empty panel.
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
    }

    public onJsonValidationChange(isValid: boolean): void {
        this.isJsonValid.set(isValid);
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
        // Table-mode edits don't touch the JSON form control until save/toggle, so
        // mark the form dirty here to make the unsaved-changes guard fire.
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
        if (!this.form.dirty) {
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
                // result === true   → "Leave" (confirm button) → close
                // result === false  → "Cancel" (cancel button) → stay
                // result === 'close' → user dismissed → stay
                if (result === true) {
                    this.dialogRef.close();
                }
            });
    }

    public makeCopy(): void {
        const original = this.selectedTool;
        if (!original || this.isCopying()) {
            return;
        }

        const variables = Array.isArray(original.variables) ? original.variables : [];
        const payload: CreatePythonCodeToolPayload = {
            name: `Copy ${original.name}`,
            description: original.description,
            variables,
            python_code: {
                code: original.python_code?.code ?? '',
                entrypoint: original.python_code?.entrypoint ?? 'main',
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
                    this.toast.error('Failed to copy custom tool. Please try again.');
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

        this.isSaving.set(true);

        const editingTool = this.selectedTool;
        const request$ = editingTool
            ? this.customToolsService.updatePythonCodeToolV2(editingTool.id, payload)
            : this.customToolsService.createPythonCodeToolV2(payload);

        const successMessage = editingTool ? 'Custom tool updated successfully!' : 'Custom tool created successfully!';
        const errorMessage = editingTool
            ? 'Failed to update custom tool. Please try again.'
            : 'Failed to create custom tool. Please try again.';

        request$
            .pipe(
                tap((result) => {
                    this.toast.success(successMessage);
                    this.dialogRef.close(result);
                }),
                catchError((err: HttpErrorResponse) => {
                    console.error(editingTool ? 'Error updating tool:' : 'Error creating tool:', err);
                    this.toast.error(errorMessage);
                    return EMPTY;
                }),
                finalize(() => this.isSaving.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    private initialVariablesJsonFromTool(tool: GetPythonCodeToolRequest): string {
        const v = tool.variables;
        const list = Array.isArray(v) ? v : [];
        return JSON.stringify(list, null, 2);
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
            return 'Fix Python code errors before saving';
        }
        return null;
    }

    private buildPayload(): CreatePythonCodeToolPayload {
        return toCreatePayload(this.form.getRawValue());
    }
}
