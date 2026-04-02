import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    ElementRef,
    Inject,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormControl,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    Validators,
} from '@angular/forms';
import {
    AppIconComponent,
    ButtonComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    HelpTooltipComponent,
    JsonEditorComponent,
} from '@shared/components';

import {
    ArgsSchema,
    CreatePythonCodeToolRequest,
    GetPythonCodeToolRequest,
    UpdatePythonCodeToolRequest,
} from '../../../features/tools/models/python-code-tool.model';
import { CustomToolsService } from '../../../features/tools/services/custom-tools/custom-tools.service';
import { ToastService } from '../../../services/notifications';
import { CodeEditorComponent } from './code-editor/code-editor.component';
import { ToolLibrariesComponent } from './tool-libraries/tool-libraries.component';

interface DialogData {
    pythonTools: GetPythonCodeToolRequest[];
    selectedTool?: GetPythonCodeToolRequest;
}

@Component({
    selector: 'app-custom-tool-dialog',
    imports: [
        ReactiveFormsModule,
        CommonModule,
        ToolLibrariesComponent,
        CodeEditorComponent,
        DialogModule,
        AppIconComponent,
        ButtonComponent,
        HelpTooltipComponent,
        JsonEditorComponent,
    ],
    templateUrl: './custom-tool-dialog.component.html',
    styleUrls: ['./custom-tool-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CustomToolDialogComponent implements OnInit, AfterViewInit {
    @ViewChild(ToolLibrariesComponent)
    toolLibrariesComponent!: ToolLibrariesComponent;
    @ViewChild(CodeEditorComponent)
    toolEditorComponent!: CodeEditorComponent;
    @ViewChild('toolNameInput')
    toolNameInput!: ElementRef<HTMLInputElement>;

    form!: FormGroup;
    public pythonCode: string =
        '# This Python code will be executed by AI agents when they use this custom tool\n# Define your tool logic in the main function - agents will call this function with the specified arguments\n# def main(arg1: str, arg2: str) -> dict:\n#    return {\n#        "result": arg1 + arg2,\n#    }\n';
    public editorHasError = false;
    public selectedVariables: Array<{
        name: string;
        description: string;
        required: boolean;
    }> = [];
    public selectedLibraries: string[] = [];
    public selectedTool?: GetPythonCodeToolRequest;

    public inputsJsonConfig = signal<string>('{}');
    public isInputsJsonValid = signal<boolean>(true);

    constructor(
        private dialogRef: DialogRef,
        private cdr: ChangeDetectorRef,
        private customToolsService: CustomToolsService,
        private toastService: ToastService,
        private confirmation: ConfirmationDialogService,
        private destroyRef: DestroyRef,
        @Inject(DIALOG_DATA) public data: DialogData
    ) {
        if (data.selectedTool) {
            this.selectedTool = data.selectedTool;
        }
    }

    ngOnInit(): void {
        // Initialize form
        this.form = new FormGroup({
            toolName: new FormControl(this.selectedTool ? this.selectedTool.name : '', [
                Validators.required,
                this.uniqueNameValidator.bind(this),
            ]),
            toolDescription: new FormControl(
                this.selectedTool ? this.selectedTool.description : '',
                Validators.required
            ),
        });

        if (this.selectedTool) {
            this.pythonCode = this.selectedTool.python_code.code;
            this.selectedLibraries = this.selectedTool.python_code.libraries || [];

            if (this.selectedTool.args_schema && this.selectedTool.args_schema.properties) {
                this.selectedVariables = Object.entries(
                    this.selectedTool.args_schema.properties
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                ).map(([name, prop]: [string, any]) => ({
                    name,
                    description: prop.description || '',
                    required: this.selectedTool?.args_schema.required?.includes(name) || false,
                }));

                const schemaWithoutType = {
                    properties: this.selectedTool.args_schema.properties,
                    required: this.selectedTool.args_schema.required || [],
                };
                this.inputsJsonConfig.set(JSON.stringify(schemaWithoutType, null, 2));
            } else {
                this.inputsJsonConfig.set(this.getDefaultInputsSchema());
            }
        } else {
            this.inputsJsonConfig.set(this.getDefaultInputsSchema());
        }

        this.cdr.markForCheck();
    }

    private getDefaultInputsSchema(): string {
        const defaultSchema = {
            properties: {},
            required: [],
        };
        return JSON.stringify(defaultSchema, null, 2);
    }

    public onInputsJsonValidChange(isValid: boolean): void {
        this.isInputsJsonValid.set(isValid);
    }

    ngAfterViewInit(): void {
        // Optionally focus the name input
        setTimeout(() => {
            this.toolNameInput?.nativeElement.focus();
        });
    }

    uniqueNameValidator(control: AbstractControl): ValidationErrors | null {
        const name = (control.value || '').trim().toLowerCase();
        if (!name) {
            return null;
        }
        const duplicateExists = this.data.pythonTools.some(
            (tool) => tool.name.toLowerCase() === name && (!this.selectedTool || tool.id !== this.selectedTool.id)
        );
        return duplicateExists ? { nonUniqueName: true } : null;
    }

    public close(): void {
        const confirmationData: ConfirmationDialogData = {
            title: 'Are you sure you want to leave?',
            message: 'All unsaved changes will be lost',
            type: 'warning',
        };

        this.confirmation
            .confirm(confirmationData)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.dialogRef.close();
                }
            });
    }

    public createTool(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid || !this.isInputsJsonValid()) {
            return;
        }

        const toolName = this.form.value.toolName;
        const toolDescription = this.form.value.toolDescription;

        let argsSchemaObj: ArgsSchema;
        try {
            const parsedInputs = JSON.parse(this.inputsJsonConfig());
            argsSchemaObj = {
                type: 'object',
                title: 'ToolInputSchema',
                properties: parsedInputs.properties || {},
                required: parsedInputs.required || [],
            };
        } catch {
            this.toastService.error('Invalid inputs JSON format');
            return;
        }

        // Prepare request data
        const toolData: CreatePythonCodeToolRequest = {
            python_code: {
                libraries: this.toolLibrariesComponent?.libraries?.length
                    ? this.toolLibrariesComponent.libraries
                    : this.selectedLibraries,
                code: this.toolEditorComponent.pythonCode,
                entrypoint: 'main',
            },
            name: toolName,
            description: toolDescription,
            args_schema: argsSchemaObj,
        };

        if (this.selectedTool) {
            // Update scenario
            const updateTool: UpdatePythonCodeToolRequest = {
                id: this.selectedTool.id,
                python_code: {
                    id: this.selectedTool.python_code.id,
                    libraries: this.toolLibrariesComponent?.libraries?.length
                        ? this.toolLibrariesComponent.libraries
                        : this.selectedLibraries,
                    code: this.toolEditorComponent.pythonCode,
                    entrypoint: 'main',
                },
                name: toolName,
                description: toolDescription,
                args_schema: argsSchemaObj,
            };
            this.customToolsService
                .updatePythonCodeTool(String(this.selectedTool.id), updateTool)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (result: GetPythonCodeToolRequest) => {
                        this.toastService.success(`Custom Tool updated successfully!`);
                        this.dialogRef.close(result);
                    },
                    error: (error: HttpErrorResponse) => {
                        console.error('Error updating tool:', error);
                        this.toastService.error('Failed to update custom tool. Please try again.');
                    },
                });
        } else {
            // Create scenario
            this.customToolsService
                .createPythonCodeTool(toolData)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (result: GetPythonCodeToolRequest) => {
                        this.toastService.success(`Custom Tool created successfully!`);
                        this.dialogRef.close(result);
                    },
                    error: (error: HttpErrorResponse) => {
                        console.error('Error creating tool:', error);
                        this.toastService.error('Failed to create custom tool. Please try again.');
                    },
                });
        }
    }

    public onEditorErrorChange(hasError: boolean): void {
        this.editorHasError = hasError;
        this.cdr.markForCheck();
    }
}
