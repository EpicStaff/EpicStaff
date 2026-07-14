import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { Component, DestroyRef, Inject, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

@Component({
    selector: 'app-edit-title-dialog',
    standalone: true,
    imports: [FormsModule, CommonModule],
    template: `
        <div class="dialog-container">
            <h2 class="dialog-title">Edit Project Name</h2>

            <div class="dialog-content">
                <input
                    type="text"
                    [(ngModel)]="data.title"
                    class="title-input"
                    placeholder="Enter project name"
                    #titleInput
                    autofocus
                />
            </div>

            <div class="dialog-actions">
                <button
                    class="cancel-button"
                    (click)="close()"
                >
                    Cancel
                </button>
                <button
                    class="save-button"
                    (click)="save()"
                    [disabled]="!isValid()"
                >
                    Save
                </button>
            </div>
        </div>
    `,
    styles: [
        `
            .dialog-container {
                padding: var(--space-2xl);
                background-color: var(--graphite-875);
                border-radius: var(--radius-2xl);
                color: #ebebeb;
                box-shadow: 0 8px 20px var(--black-alpha-40);
            }

            .dialog-title {
                margin-top: 0;
                font-size: var(--font-size-xl);
                font-weight: var(--font-weight-medium);
                margin-bottom: var(--space-lg);
            }

            .dialog-content {
                margin-bottom: var(--space-2xl);
            }

            .title-input {
                width: 100%;
                padding: var(--space-md) var(--space-md);
                background-color: var(--white-alpha-10);
                border: 1px solid var(--white-alpha-20);
                border-radius: var(--radius-md);
                color: var(--white);
                font-size: var(--font-size-lg);
                outline: none;
                transition: all 0.2s ease;
            }

            .title-input:focus {
                border-color: var(--purple-alpha-80);
                background-color: var(--purple-alpha-10);
            }

            .dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: var(--space-md);
            }

            button {
                padding: var(--space-sm) var(--space-lg);
                border-radius: var(--radius-md);
                font-size: var(--font-size-md);
                font-weight: var(--font-weight-medium);
                cursor: pointer;
                transition: all 0.2s ease;
            }

            button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .cancel-button {
                background: transparent;
                border: 1px solid var(--white-alpha-20);
                color: #ebebeb;
            }

            .cancel-button:hover:not(:disabled) {
                background: var(--white-alpha-10);
            }

            .save-button {
                background: linear-gradient(135deg, var(--accent-color), #896fff);
                border: none;
                color: var(--white);
            }

            .save-button:hover:not(:disabled) {
                background: linear-gradient(135deg, #7469ff, #9c82ff);
                transform: translateY(-1px);
            }
        `,
    ],
})
export class EditTitleDialogComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);

    constructor(
        public dialogRef: DialogRef<string>,
        @Inject(DIALOG_DATA) public data: { title: string }
    ) {}

    ngOnInit(): void {
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.save();
            }
        });
    }

    isValid(): boolean {
        return !!(this.data.title && this.data.title.trim());
    }

    save(): void {
        if (this.isValid()) {
            this.dialogRef.close(this.data.title.trim());
        }
    }

    close(): void {
        this.dialogRef.close();
    }
}
