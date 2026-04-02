import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, Inject, inject, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { of, Subscription } from 'rxjs';
import { finalize, map, switchMap } from 'rxjs/operators';

import { CreateGraphDtoRequest, GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { LabelDropdownComponent } from '../label-dropdown/label-dropdown.component';

export interface FlowDialogData {
    isEdit: boolean;
    flow?: GraphDto;
}

@Component({
    selector: 'app-create-flow-dialog',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, ButtonComponent, LabelDropdownComponent],
    templateUrl: './create-flow-dialog.component.html',
    styleUrls: ['./create-flow-dialog.component.scss'],
})
export class CreateFlowDialogComponent implements OnInit, OnDestroy {
    flowForm: FormGroup;
    isEditMode = false;
    dialogTitle = 'Create New Flow';
    submitButtonText = 'Create';
    originalFlow?: GraphDto;
    public selectedIcon: string | null = null;
    public isSubmitting = false;
    public errorMessage: string | null = null;

    private flowsStorageService = inject(FlowsStorageService);
    
    @ViewChild(LabelDropdownComponent)
    private labelDropdown?: LabelDropdownComponent;
    private keydownSubscription?: Subscription;

    constructor(
        public dialogRef: DialogRef<GraphDto | undefined>,
        @Inject(DIALOG_DATA) public data: FlowDialogData
    ) {
        this.flowForm = new FormGroup({
            name: new FormControl('', [Validators.required]),
            description: new FormControl(''),
            flow_icon: new FormControl(''),
            label_ids: new FormControl<number[]>([]),
        });

        if (data && data.isEdit && data.flow) {
            this.isEditMode = true;
            this.dialogTitle = 'Edit Flow';
            this.submitButtonText = 'Save';
            this.originalFlow = data.flow;
        }
    }

    ngOnInit(): void {
        if (this.isEditMode && this.data.flow) {
            this.flowForm.patchValue({
                name: this.data.flow.name,
                description: this.data.flow.description || '',
                flow_icon:
                    ((this.data.flow.metadata as unknown as Record<string, unknown>)?.['flow_icon'] as string) || '',
                label_ids: this.data.flow.label_ids || [],
            });
            this.selectedIcon =
                ((this.data.flow.metadata as unknown as Record<string, unknown>)?.['flow_icon'] as string) || null;
        }

        this.keydownSubscription = this.dialogRef.keydownEvents.subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                if (this.labelDropdown?.isOpen()) {
                    return;
                }
                event.preventDefault();
                event.stopPropagation();
                this.onSubmit();
            }
        });
    }

    ngOnDestroy(): void {
        this.keydownSubscription?.unsubscribe();
    }

    onSubmit(): void {
        if (this.flowForm.invalid || this.isSubmitting) {
            this.flowForm.markAllAsTouched();
            return;
        }

        this.isSubmitting = true;
        this.errorMessage = null;

        const formValue = this.flowForm.value;

        if (this.isEditMode && this.originalFlow) {
            this.flowsStorageService
                .patchUpdateFlow(this.originalFlow.id, {
                    name: formValue.name,
                    description: formValue.description || '',
                })
                .pipe(
                    switchMap((updatedFlow) => {
                        const labelIds: number[] = formValue.label_ids || [];
                        return this.flowsStorageService
                            .updateFlowLabels(updatedFlow.id, labelIds)
                            .pipe(map(() => updatedFlow));
                    }),
                    finalize(() => (this.isSubmitting = false))
                )
                .subscribe({
                    next: (updatedFlow) => this.dialogRef.close(updatedFlow),
                    error: () => (this.errorMessage = 'Failed to update flow. Please try again.'),
                });
            return;
        }

        // Default metadata for a new flow
        const newFlowMetadata: Record<string, unknown> = {
            flow_icon: formValue.flow_icon || undefined,
            nodes: [],
            connections: [],
            groups: [],
        };

        const requestData: CreateGraphDtoRequest = {
            name: formValue.name,
            description: formValue.description || undefined,
            metadata: newFlowMetadata,
        };

        this.flowsStorageService
            .createFlow(requestData)
            .pipe(
                switchMap((newFlow) => {
                    const labelIds: number[] = formValue.label_ids || [];
                    if (labelIds.length === 0) return of(newFlow);
                    return this.flowsStorageService.updateFlowLabels(newFlow.id, labelIds).pipe(map(() => newFlow));
                }),
                finalize(() => (this.isSubmitting = false))
            )
            .subscribe({
                next: (newFlow: GraphDto) => {
                    this.dialogRef.close(newFlow);
                },
                error: (error) => {
                    console.error('Error creating flow:', error);
                    this.errorMessage = 'Failed to create flow. Please try again.';
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onIconSelected(icon: string | null): void {
        this.selectedIcon = icon;
        this.flowForm.get('flow_icon')?.setValue(icon || '');
    }
}
