import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
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
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    HintMessageComponent,
    IconButtonComponent,
    InputNumberComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective, HasPermissionDirective } from '@shared/directives';
import { httpUrlValidator, notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, CreateMcpToolRequest, GetMcpToolRequest, ResourceCode } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable, of, timer } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { McpToolsService } from '../../services/mcp-tools/mcp-tools.service';

interface DialogData {
    selectedTool?: GetMcpToolRequest;
}

@Component({
    selector: 'app-mcp-tool-dialog',
    imports: [
        ReactiveFormsModule,
        DialogModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        EnterSubmitDirective,
        HasPermissionDirective,
        HintMessageComponent,
        IconButtonComponent,
        InputNumberComponent,
        SelectComponent,
        ValidationErrorsComponent,
    ],
    templateUrl: './mcp-tool-dialog.component.html',
    styleUrls: ['./mcp-tool-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolDialogComponent implements OnInit {
    public readonly canUseSecrets = computed(() => this.permissionsService.can(ResourceCode.Secrets, ActionCode.Use));

    public readonly secretItems = computed<SelectItem[]>(() => [
        { name: 'No secret', value: null },
        ...this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        })),
    ]);

    form!: FormGroup;
    public selectedTool?: GetMcpToolRequest;
    public isEditMode: boolean = false;
    public backendErrorMessage: string | null = null;
    private readonly destroyRef = inject(DestroyRef);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly permissionsService = inject(PermissionsService);

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
            const name = typeof control.value === 'string' ? control.value.trim() : '';
            if (!name) {
                return of(null);
            }

            // If in edit mode and name hasn't changed, skip validation
            if (this.isEditMode && name === this.selectedTool?.name) {
                return of(null);
            }

            // Debounce for 500ms before making the API call
            return timer(500).pipe(
                switchMap(() =>
                    this.mcpToolsService.getMcpTools({ name }).pipe(
                        map((tools) => {
                            const nameExists = tools.some((tool) => tool.name === name);
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
                [Validators.required, Validators.minLength(1), Validators.maxLength(255), notWhitespaceValidator()],
                [this.uniqueNameValidator()]
            ),
            transport: new FormControl(this.selectedTool?.transport || '', [
                Validators.required,
                Validators.maxLength(2048),
                httpUrlValidator(),
            ]),
            tool_name: new FormControl(this.selectedTool?.tool_name || '', [
                Validators.required,
                Validators.maxLength(255),
            ]),
            timeout: new FormControl(this.selectedTool?.timeout ?? 30, [
                Validators.required,
                Validators.min(1),
                Validators.max(1800),
            ]),
            auth_secret_id: new FormControl(this.selectedTool?.auth_secret_id ?? null),
            init_timeout: new FormControl(this.selectedTool?.init_timeout ?? 10, [
                Validators.required,
                Validators.min(1),
                Validators.max(120),
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

        const toolData: CreateMcpToolRequest = {
            name: formValue.name.trim(),
            transport: formValue.transport.trim(),
            tool_name: formValue.tool_name.trim(),
            timeout: formValue.timeout ?? 30,
            auth_secret_id: this.canUseSecrets()
                ? (formValue.auth_secret_id ?? null)
                : (this.selectedTool?.auth_secret_id ?? null),
            init_timeout: formValue.init_timeout ?? 10,
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
