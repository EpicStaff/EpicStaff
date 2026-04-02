import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize, map, switchMap } from 'rxjs/operators';

import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { FlowsStorageService } from '../../services/flows-storage.service';
import { LabelDropdownComponent } from '../label-dropdown/label-dropdown.component';

interface FlowRenameData {
    flowName: string;
    title?: string;
    flow?: { id: number; name: string; description: string; label_ids?: number[] };
}

@Component({
    selector: 'app-flow-rename-dialog',
    standalone: true,
    imports: [CommonModule, FormsModule, ButtonComponent, LabelDropdownComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="dialog-container">
            <h2 class="dialog-title">{{ data.title || 'Edit Flow' }}</h2>
            <div class="dialog-content">
                <div class="form-group">
                    <label for="flowName">Flow Name</label>
                    <input
                        type="text"
                        id="flowName"
                        class="form-control"
                        [(ngModel)]="newName"
                        required
                        placeholder="Enter flow name"
                        autocomplete="off"
                    />
                </div>
                @if (data.flow) {
                    <div class="form-group">
                        <label>Labels</label>
                        <app-label-dropdown
                            [selectedLabelIds]="selectedLabelIds"
                            (selectionChange)="selectedLabelIds = $event"
                        ></app-label-dropdown>
                    </div>
                    <div class="form-group">
                        <label for="flowDescription">Description</label>
                        <textarea
                            id="flowDescription"
                            class="form-control"
                            [(ngModel)]="description"
                            placeholder="Enter flow description (optional)"
                            rows="3"
                        ></textarea>
                    </div>
                }
            </div>
            @if (errorMessage) {
                <div class="error-message-block">{{ errorMessage }}</div>
            }
            <div class="dialog-actions">
                <app-button type="ghost" (click)="cancel()">Cancel</app-button>
                <app-button type="primary" [disabled]="!newName || !newName.trim().length" (click)="save()"
                    >Save</app-button
                >
            </div>
        </div>
    `,
    styles: [
        `
            .dialog-container {
                background: var(--color-sidenav-background);
                border-radius: 12px;
                padding: 1.5rem;
                width: 500px;
                max-width: 100%;
            }

            .dialog-title {
                margin-top: 0;
                margin-bottom: 1.5rem;
                color: var(--color-text-primary);
                font-size: 1.25rem;
                font-weight: 600;
            }

            .dialog-content {
                margin-bottom: 1.5rem;
            }

            .form-group {
                margin-bottom: 1rem;
            }

            label {
                display: block;
                margin-bottom: 0.5rem;
                color: var(--color-text-secondary);
                font-size: 0.875rem;
            }

            .form-control {
                width: 100%;
                padding: 0.625rem;
                background-color: var(--color-input-background);
                border: 1px solid var(--color-input-border);
                border-radius: 6px;
                color: var(--color-text-primary);
                font-size: 0.875rem;
                transition: border-color 0.2s;
                resize: vertical;
                box-sizing: border-box;
            }

            .form-control:focus {
                outline: none;
                border-color: var(--accent-color);
            }

            .dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: 0.75rem;
            }

            .error-message-block {
                padding: 0.5rem 0.75rem;
                color: var(--color-error);
                font-size: 12px;
                margin-top: 4px;
            }
        `,
    ],
})
export class FlowRenameDialogComponent implements OnInit {
    private readonly dialogRef = inject(DialogRef);
    private readonly cdr = inject(ChangeDetectorRef);
    public readonly data = inject<FlowRenameData>(DIALOG_DATA);
    private readonly flowsStorage = inject(FlowsStorageService);

    public newName = this.data.flowName;
    public description = '';
    public selectedLabelIds: number[] = [];
    public errorMessage = '';
    public isSubmitting = false;

    public isValid = signal<boolean>(true);

    ngOnInit(): void {
        if (this.data.flow) {
            this.description = this.data.flow.description || '';
            this.selectedLabelIds = [...(this.data.flow.label_ids || [])];
        }
        this.validateName();
    }

    private validateName(): void {
        this.isValid.set(!!this.newName && this.newName.trim().length > 0);
    }

    public save(): void {
        this.validateName();
        if (!this.isValid()) return;

        if (this.data.flow) {
            this.isSubmitting = true;
            this.errorMessage = '';
            this.cdr.markForCheck();

            this.flowsStorage
                .patchUpdateFlow(this.data.flow.id, {
                    name: this.newName,
                    description: this.description,
                })
                .pipe(
                    switchMap((updatedFlow) =>
                        this.flowsStorage
                            .updateFlowLabels(updatedFlow.id, this.selectedLabelIds)
                            .pipe(map(() => updatedFlow))
                    ),
                    finalize(() => {
                        this.isSubmitting = false;
                        this.cdr.markForCheck();
                    })
                )
                .subscribe({
                    next: (updatedFlow) => this.dialogRef.close(updatedFlow),
                    error: () => {
                        this.errorMessage = 'Failed to update flow. Please try again.';
                        this.cdr.markForCheck();
                    },
                });
        } else {
            this.dialogRef.close(this.newName);
        }
    }

    public cancel(): void {
        this.dialogRef.close();
    }
}
