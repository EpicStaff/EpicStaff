import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, DestroyRef, inject, Inject, OnInit } from '@angular/core';
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
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
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
    standalone: true,
    imports: [
        ReactiveFormsModule,
        CommonModule,
        DialogModule,
        MatFormFieldModule,
        MatInputModule,
        MatButtonModule,
        MatTooltipModule,
        AppSvgIconComponent,
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
        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((event: KeyboardEvent) => {
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
            timeout: new FormControl(this.selectedTool?.timeout ?? 30),
            auth: new FormControl(this.selectedTool?.auth || ''),
            init_timeout: new FormControl(this.selectedTool?.init_timeout ?? 10),
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
            auth: formValue.auth || undefined,
            init_timeout: formValue.init_timeout || undefined,
        };

        if (this.isEditMode && this.selectedTool) {
            this.mcpToolsService.updateMcpTool(this.selectedTool.id, toolData).subscribe({
                next: (updatedTool) => {
                    this.toastService.success(`MCP tool "${updatedTool.name}" updated successfully!`);
                    this.dialogRef.close(updatedTool);
                },
                error: (error) => {
                    console.error('Error updating MCP tool:', error);
                    this.backendErrorMessage = this.extractErrorMessage(error);
                    this.toastService.error(this.backendErrorMessage || 'Failed to update MCP tool. Please try again.');
                    this.cdr.markForCheck();
                },
            });
        } else {
            this.mcpToolsService.createMcpTool(toolData).subscribe({
                next: (createdTool) => {
                    this.toastService.success(`MCP tool "${createdTool.name}" created successfully!`);
                    this.dialogRef.close(createdTool);
                },
                error: (error) => {
                    console.error('Error creating MCP tool:', error);
                    this.backendErrorMessage = this.extractErrorMessage(error);
                    this.toastService.error(this.backendErrorMessage || 'Failed to create MCP tool. Please try again.');
                    this.cdr.markForCheck();
                },
            });
        }
    }

    private extractErrorMessage(error: unknown): string {
        const err = error as Record<string, Record<string, unknown> | string | undefined>;
        // Extract error message from different possible error structures
        if (err?.['error']) {
            const errBody = err['error'] as Record<string, unknown>;
            // Check for standard error message formats
            if (typeof errBody === 'string') {
                return errBody;
            }
            if (errBody['message']) {
                return errBody['message'] as string;
            }
            if (errBody['detail']) {
                return errBody['detail'] as string;
            }
            // Check for field-specific errors (e.g., {name: ["Tool with this name already exists."]})
            if (errBody['name'] && Array.isArray(errBody['name'])) {
                return (errBody['name'] as string[])[0];
            }
            // Check for non_field_errors
            if (errBody['non_field_errors'] && Array.isArray(errBody['non_field_errors'])) {
                return (errBody['non_field_errors'] as string[])[0];
            }
        }
        if (err?.['message']) {
            return err['message'] as string;
        }
        if (err?.['statusText']) {
            return err['statusText'] as string;
        }
        return '';
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
}
