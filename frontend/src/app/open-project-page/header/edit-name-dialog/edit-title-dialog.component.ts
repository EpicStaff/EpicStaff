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
                padding: 24px;
                background-color: #1e1e1e;
                border-radius: 12px;
                color: #ebebeb;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
            }

            .dialog-title {
                margin-top: 0;
                font-size: 18px;
                font-weight: 500;
                margin-bottom: 16px;
            }

            .dialog-content {
                margin-bottom: 24px;
            }

            .title-input {
                width: 100%;
                padding: 10px 12px;
                background-color: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                color: #ffffff;
                font-size: 16px;
                outline: none;
                transition: all 0.2s ease;
            }

            .title-input:focus {
                border-color: rgba(104, 95, 255, 0.8);
                background-color: rgba(104, 95, 255, 0.1);
            }

            .dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: 12px;
            }

            button {
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s ease;
            }

            button:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .cancel-button {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.2);
                color: #ebebeb;
            }

            .cancel-button:hover:not(:disabled) {
                background: rgba(255, 255, 255, 0.1);
            }

            .save-button {
                background: linear-gradient(135deg, #685fff, #896fff);
                border: none;
                color: #ffffff;
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
