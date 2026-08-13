import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    computed,
    DestroyRef,
    Inject,
    inject,
    OnInit,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    AsyncValidatorFn,
    FormControl,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
    Validators,
} from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HintMessageComponent,
    IconButtonComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable, of, timer } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CreateMcpToolRequest, GetMcpToolRequest } from '../../models/mcp-tool.model';
import { McpToolsService } from '../../services/mcp-tools/mcp-tools.service';

interface DialogData {
    selectedTool?: GetMcpToolRequest;
}

@Component({
    selector: 'app-mcp-tool-dialog',
    imports: [
        ReactiveFormsModule,
        CommonModule,
        DialogModule,
        AppSvgIconComponent,
        CustomInputComponent,
        ValidationErrorsComponent,
        InputNumberComponent,
        ButtonComponent,
        IconButtonComponent,
        HasPermissionDirective,
        SelectComponent,
        HintMessageComponent,
    ],
    templateUrl: './mcp-tool-dialog.component.html',
    styleUrls: ['./mcp-tool-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolDialogComponent implements OnInit {
    form!: FormGroup;
    public selectedTool?: GetMcpToolRequest;
    public isEditMode: boolean = false;
    public backendErrorMessage: string | null = null;
    private readonly destroyRef = inject(DestroyRef);
    private readonly secretsStorageService = inject(SecretsStorageService);

    constructor(
        private dialogRef: DialogRef<GetMcpToolRequest>,
        private cdr: ChangeDetectorRef,
        private mcpToolsService: McpToolsService,
        private toastService: ToastService,
        @Inject(DIALOG_DATA) public data: DialogData
    ) {
        if (data?.selectedTool) {
            this.selectedTool = data.selectedTool;
            this.isEditMode = true;
        }
    }

    public readonly secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    ngOnInit(): void {
        this.initializeForm();
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toastService.error('Failed to load secrets.'),
            });
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                if (this.form.status === 'PENDING') return;
                event.preventDefault();
                this.onSave();
            }
        });
    }

    private uniqueNameValidator(): AsyncValidatorFn {
        return (control: AbstractControl): Observable<ValidationErrors | null> => {
            if (!control.value) {
                return of(null);
            }

            // If in edit mode and name hasn't changed, skip validation
            if (this.isEditMode && control.value === this.selectedTool?.name) {
                return of(null);
            }

            // Debounce for 500ms before making the API call
            return timer(500).pipe(
                switchMap(() =>
                    this.mcpToolsService.getMcpTools({ name: control.value }).pipe(
                        map((tools) => {
                            const nameExists = tools.some((tool) => tool.name === control.value);
                            return nameExists ? { uniqueName: true } : null;
                        }),
                        catchError(() => of(null))
                    )
                )
            );
        };
    }

    private initializeForm(): void {
        this.form = new FormGroup({
            name: new FormControl(
                this.selectedTool?.name || '',
                [Validators.required, Validators.minLength(1), Validators.maxLength(255)],
                [this.uniqueNameValidator()]
            ),
            transport: new FormControl(this.selectedTool?.transport || '', [
                Validators.required,
                Validators.maxLength(2048),
            ]),
            tool_name: new FormControl(this.selectedTool?.tool_name || '', [
                Validators.required,
                Validators.maxLength(255),
            ]),
            timeout: new FormControl(this.selectedTool?.timeout ?? 30, [Validators.min(1), Validators.max(2147483647)]),
            auth_secret_id: new FormControl(this.selectedTool?.auth_secret_id ?? null),
            init_timeout: new FormControl(this.selectedTool?.init_timeout ?? 10, [
                Validators.min(1),
                Validators.max(2147483647),
            ]),
        });
    }

    public onCancel(): void {
        this.dialogRef.close(undefined);
    }

    public onSave(): void {
        if (this.form.invalid) {
            this.toastService.error('Please fill in all required fields correctly.');
            this.form.markAllAsTouched();
            this.cdr.markForCheck();
            return;
        }

        // Clear previous backend error message
        this.backendErrorMessage = null;

        const formValue = this.form.value;

        // Clean up empty values
        const toolData: CreateMcpToolRequest = {
            name: formValue.name,
            transport: formValue.transport,
            tool_name: formValue.tool_name,
            timeout: formValue.timeout || undefined,
            auth_secret_id: formValue.auth_secret_id || undefined,
            init_timeout: formValue.init_timeout || undefined,
        };

        if (this.isEditMode && this.selectedTool) {
            this.mcpToolsService.updateMcpTool(this.selectedTool.id, toolData).subscribe({
                next: (updatedTool) => {
                    this.toastService.success(`MCP tool "${updatedTool.name}" updated successfully!`);
                    this.dialogRef.close(updatedTool);
                },
                error: (error: HttpErrorResponse) => {
                    console.error('Error updating MCP tool:', error);
                    this.backendErrorMessage = extractHttpErrorMessage(error);
                    this.toastService.error(this.backendErrorMessage);
                    this.cdr.markForCheck();
                },
            });
        } else {
            this.mcpToolsService.createMcpTool(toolData).subscribe({
                next: (createdTool) => {
                    this.toastService.success(`MCP tool "${createdTool.name}" created successfully!`);
                    this.dialogRef.close(createdTool);
                },
                error: (error: HttpErrorResponse) => {
                    console.error('Error creating MCP tool:', error);
                    this.backendErrorMessage = extractHttpErrorMessage(error);
                    this.toastService.error(this.backendErrorMessage);
                    this.cdr.markForCheck();
                },
            });
        }
    }

    public getFieldError(fieldName: string): string | null {
        const field = this.form.get(fieldName);
        if (field?.invalid && (field?.dirty || field?.touched)) {
            if (field.errors?.['required']) {
                return 'This field is required';
            }
            if (field.errors?.['minlength']) {
                return `Minimum length is ${field.errors['minlength'].requiredLength}`;
            }
            if (field.errors?.['maxlength']) {
                return `Maximum length is ${field.errors['maxlength'].requiredLength}`;
            }
            if (field.errors?.['uniqueName']) {
                return 'A tool with this name already exists';
            }
        }
        return null;
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
