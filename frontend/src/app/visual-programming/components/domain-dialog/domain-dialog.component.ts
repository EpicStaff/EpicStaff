import { Component, Inject, ViewEncapsulation } from '@angular/core';
import { CommonModule } from '@angular/common';
import { JsonEditorComponent } from '../../../shared/components/json-editor/json-editor.component';
import { DialogRef, DIALOG_DATA } from '@angular/cdk/dialog';

export interface DomainDialogData {
    initialData: Record<string, unknown>;
}

@Component({
    standalone: true,
    selector: 'app-domain-dialog',
    imports: [CommonModule, JsonEditorComponent],
    encapsulation: ViewEncapsulation.None,
    template: `
        <div class="dialog-container">
            <div class="dialog-header">
                <h2 class="dialog-title">Domain Variables</h2>
                <button class="close-button" (click)="onClose()">
                    <i class="ti ti-x"></i>
                </button>
            </div>

            <div class="dialog-content">
                <!-- Helper Text -->
                <div class="helper-text">
                    Here you can define your domain variables that will be
                    available throughout your workflow execution.
                </div>

                <!-- Initial State JSON Editor -->
                <div class="json-editor-section">
                    <app-json-editor
                        class="json-editor"
                        [jsonData]="initialStateJson"
                        (jsonChange)="onInitialStateChange($event)"
                        (validationChange)="onJsonValidChange($event)"
                        [fullHeight]="true"
                    ></app-json-editor>
                </div>
            </div>

            <div class="dialog-actions">
                <button class="btn-secondary" (click)="onClose()">Close</button>
                <button
                    class="btn-primary"
                    [disabled]="!isJsonValid"
                    (click)="onSave()"
                >
                    Save
                </button>
            </div>
        </div>
    `,
    styles: [
        `
            .dialog-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 0;
                background: var(--color-surface-card, #232323);
                border-radius: 8px;
                overflow: hidden;
            }

            .domain-dialog-panel {
                z-index: 9600 !important;
            }

            .dialog-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 1rem 1.5rem;
                border-bottom: 1px solid var(--color-divider-subtle, #444);
            }

            .dialog-title {
                font-size: 1.2rem;
                font-weight: 400;
                color: var(--color-text-primary, #fff);
                margin: 0;
            }

            .close-button {
                background: none;
                border: none;
                color: var(--color-text-secondary, #aaa);
                cursor: pointer;
                padding: 0.5rem;
                border-radius: 4px;
                transition: all 0.2s ease;
                display: flex;
                align-items: center;
                justify-content: center;
                line-height: 1;

                &:hover {
                    background: var(--color-surface-hover, #333);
                    color: var(--color-text-primary, #fff);
                }

                i {
                    font-size: 1.25rem;

                    display: flex;
                    align-items: center;
                    justify-content: center;
                }
            }

            .dialog-content {
                flex: 1;
                padding: 1.5rem;
                overflow: hidden;
                display: flex;
                flex-direction: column;
            }

            .helper-text {
                color: #6b7280;
                font-size: 0.875rem;
                line-height: 1.4;
                margin-bottom: 1.5rem;
            }

            .json-editor-section {
                flex: 1;
                min-height: 400px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
            }

            .json-editor {
                height: 100%;
            }

            .dialog-actions {
                display: flex;
                justify-content: flex-end;
                gap: 0.75rem;
                padding: 1rem 1.5rem;
                border-top: 1px solid var(--color-divider-subtle, #444);
            }

            .btn-primary {
                background-color: var(--accent-color, #6562f5);
                color: white;
                border: 1px solid var(--accent-color, #6562f5);
                padding: 0.5rem 1rem;
                border-radius: 6px;
                font-size: 0.875rem;
                font-weight: 400;
                cursor: pointer;
                transition: all 0.2s ease;

                &:hover:not(:disabled) {
                    background-color: #5a5ae0;
                    border-color: #5a5ae0;
                }

                &:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
            }

            .btn-secondary {
                background-color: transparent;
                color: var(--color-text-primary, #fff);
                border: 1px solid var(--color-divider-subtle, #444);
                padding: 0.5rem 1rem;
                border-radius: 6px;
                font-size: 0.875rem;
                font-weight: 400;
                cursor: pointer;
                transition: all 0.2s ease;

                &:hover {
                    background-color: var(--color-surface-hover, #333);
                }
            }
        `,
    ],
})
export class DomainDialogComponent {
    public initialStateJson: string = '{}';
    public isJsonValid: boolean = true;

    constructor(
        private dialogRef: DialogRef<Record<string, unknown> | null>,
        @Inject(DIALOG_DATA) public data: DomainDialogData
    ) {
        this.initializeJsonEditor();
    }

    private initializeJsonEditor(): void {
        const initial = this.data?.initialData as
            | Record<string, unknown>
            | undefined;
        const isEmptyObject =
            initial && typeof initial === 'object' && !Array.isArray(initial)
                ? Object.keys(initial).length === 0
                : true;

        if (initial && !isEmptyObject) {
            try {
                this.initialStateJson = JSON.stringify(initial, null, 2);
                this.isJsonValid = true;
            } catch (e) {
                this.initialStateJson = JSON.stringify(
                    { context: null },
                    null,
                    2
                );
                this.isJsonValid = false;
            }
        } else {
            this.initialStateJson = JSON.stringify({ context: null }, null, 2);
            this.isJsonValid = true;
        }
    }

    public onInitialStateChange(json: string): void {
        this.initialStateJson = json;
    }

    public onJsonValidChange(isValid: boolean): void {
        this.isJsonValid = isValid;
    }

    public onSave(): void {
        if (!this.isJsonValid) {
            return;
        }

        try {
            let parsedData: unknown = JSON.parse(this.initialStateJson);
            if (
                parsedData &&
                typeof parsedData === 'object' &&
                !Array.isArray(parsedData) &&
                Object.keys(parsedData as Record<string, unknown>).length === 0
            ) {
                parsedData = { context: null } as Record<string, unknown>;
            }
            this.dialogRef.close(parsedData as Record<string, unknown>);
        } catch (e) {
            this.dialogRef.close({ context: null } as Record<string, unknown>);
        }
    }

    public onClose(): void {
        this.dialogRef.close(null);
    }
}
