import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';

import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';
import { StartNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';

@Component({
    standalone: true,
    selector: 'app-start-node-panel',
    imports: [ReactiveFormsModule, JsonEditorComponent, CommonModule],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <form
                    [formGroup]="form"
                    class="form-container"
                >
                    <!-- Helper Text -->
                    <div class="helper-text">
                        Here you can define your domain variables that will be available throughout your workflow
                        execution.
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
                </form>
            </div>
        </div>
    `,
    styles: [
        `
            @use '../../../styles/node-panel-mixins.scss' as mixins;

            .panel-container {
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 0;
            }

            .panel-content {
                @include mixins.panel-content;
            }

            .section-header {
                @include mixins.section-header;
            }

            .form-container {
                @include mixins.form-container;
            }

            .btn-primary {
                @include mixins.primary-button;
            }

            .btn-secondary {
                @include mixins.secondary-button;
            }

            .helper-text {
                color: #6b7280;
                font-size: 0.875rem;
                line-height: 1.4;
            }

            .json-editor-section {
                height: 100%;
                min-height: 400px;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                overflow: hidden;
            }

            .json-editor {
                height: 100%;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StartNodePanelComponent extends BaseSidePanel<StartNodeModel> {
    public initialStateJson: string = '{}';
    public initialJsonState: string = '{}';
    public isJsonValid: boolean = true;

    constructor() {
        super();
    }

    public onInitialStateChange(json: string): void {
        this.initialStateJson = json;
    }

    public onCodeErrorChange(hasError: boolean): void {
        this.isJsonValid = !hasError;
    }

    public onJsonValidChange(isValid: boolean): void {
        this.isJsonValid = isValid;
    }

    public resetToOriginalState(): void {
        this.initialStateJson = this.initialJsonState;
        this.isJsonValid = true;
    }

    protected initializeForm(): FormGroup {
        const form = this.fb.group({
            // Start nodes don't have editable form fields, just the JSON editor
        });

        // Initialize the JSON editor with existing data or default empty object
        if (this.node().data?.initialState) {
            try {
                // Always stringify the object since initialState is typed as Record<string, unknown>
                this.initialStateJson = JSON.stringify(this.node().data.initialState, null, 2);
                this.isJsonValid = true;
            } catch (e) {
                console.error('Error parsing initial state JSON:', e);
                // If the original data is corrupted, use a safe default
                this.initialStateJson = '{}';
                this.isJsonValid = false;
            }
        } else {
            // No initial state, use empty object
            this.initialStateJson = '{}';
            this.isJsonValid = true;
        }

        this.initialJsonState = this.initialStateJson;

        return form;
    }

    /**
     * This method provides the specific data payload
     * for a StartNode when the inherited onSave() method is called.
     */
    protected createUpdatedNode(): StartNodeModel {
        // Parse the JSON for initialState
        let initialState = {};
        try {
            initialState = JSON.parse(this.initialStateJson);
        } catch (e) {
            console.error('Error parsing JSON:', e);
            // If parsing fails, fall back to the original data
            initialState = this.node().data?.initialState || {};
        }

        return {
            ...this.node(),
            // Keep the original node_name - no changes allowed for start nodes
            data: {
                ...this.node().data,
                initialState: initialState,
            },
        };
    }
}
