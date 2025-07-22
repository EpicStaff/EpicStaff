import { Component, Inject, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import {
  GraphDto,
  CreateGraphDtoRequest,
} from '../../../../features/flows/models/graph.model';
import { FlowsStorageService } from '../../../../features/flows/services/flows-storage.service';
import { finalize } from 'rxjs/operators';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';

export interface FlowDialogData {
  isEdit: boolean;
  flow?: GraphDto;
}

@Component({
  selector: 'app-create-flow-dialog',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, ButtonComponent],
  templateUrl: './create-flow-dialog.component.html',
  styleUrls: ['./create-flow-dialog.component.scss'],
})
export class CreateFlowDialogComponent implements OnInit {
  flowForm: FormGroup;
  isEditMode = false;
  dialogTitle = 'Create New Flow';
  submitButtonText = 'Create';
  originalFlow?: GraphDto;
  public selectedIcon: string | null = null;
  public isSubmitting = false;
  public errorMessage: string | null = null;

  private flowsStorageService = inject(FlowsStorageService);

  constructor(
    public dialogRef: DialogRef<GraphDto | undefined>,
    @Inject(DIALOG_DATA) public data: FlowDialogData
  ) {
    this.flowForm = new FormGroup({
      name: new FormControl('', [Validators.required]),
      description: new FormControl(''),
      flow_icon: new FormControl(''),
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
        flow_icon: (this.data.flow.metadata as any)?.flow_icon || '',
      });
      this.selectedIcon = (this.data.flow.metadata as any)?.flow_icon || null;
    }
  }

  onSubmit(): void {
    if (this.flowForm.invalid || this.isSubmitting) {
      return;
    }
    this.isSubmitting = true;
    this.errorMessage = null;

    const formValue = this.flowForm.value;

    // Default metadata for a new flow
    const newFlowMetadata: any = {
      flow_icon: formValue.flow_icon || undefined,
      nodes: [],
      connections: [],
      groups: [],
    };

    if (this.isEditMode && this.originalFlow) {
      const updateRequest: any = {
        ...this.originalFlow,
        name: formValue.name,
        description: formValue.description || '',
        // When editing, preserve existing metadata and update only the icon, or merge if needed.
        // For now, we are just updating/adding flow_icon to existing metadata.
        metadata: {
          ...(this.originalFlow.metadata || {}),
          flow_icon: formValue.flow_icon || undefined,
        },
      };
      console.warn(
        'Update functionality not fully implemented in this refactor. Metadata merging for edit needs review.'
      );
      // this.flowsStorageService.updateFlow(updateRequest).pipe(...)
      this.isSubmitting = false;
      // this.dialogRef.close(updatedFlow);
    } else {
      const requestData: CreateGraphDtoRequest = {
        name: formValue.name,
        description: formValue.description || undefined,
        metadata: newFlowMetadata, // Use the structured metadata for new flows
      };
      this.flowsStorageService
        .createFlow(requestData)
        .pipe(finalize(() => (this.isSubmitting = false)))
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
  }

  onCancel(): void {
    this.dialogRef.close();
  }

  onIconSelected(icon: string | null): void {
    this.selectedIcon = icon;
    this.flowForm.get('flow_icon')?.setValue(icon || '');
  }
}
