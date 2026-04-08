import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';

import { JsonEditorComponent } from '../../../../shared/components/json-editor/json-editor.component';
import { EndNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';

@Component({
    standalone: true,
    selector: 'app-end-node-panel',
    imports: [ReactiveFormsModule, JsonEditorComponent, CommonModule],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <div class="form-container">
                    <!-- Output Map Title -->
                    <div class="output-map-container">
                        <div class="label-container">
                            <label>Output Map</label>
                        </div>
                        <app-json-editor
                            class="json-editor"
                            [jsonData]="outputMapJson"
                            (jsonChange)="onOutputMapChange($event)"
                            (validationChange)="onOutputMapValidChange($event)"
                            [fullHeight]="false"
                        ></app-json-editor>
                    </div>
                </div>
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

            .label-container {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.25rem;
            }

            .label-container label {
                display: block;
                font-size: 14px;
                color: rgba(255, 255, 255, 0.7);
                margin: 0;
            }

            :host ::ng-deep app-json-editor .editor-header {
                padding-top: 0.25rem;
                padding-bottom: 0.25rem;
            }

            .output-map-container {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EndNodePanelComponent extends BaseSidePanel<EndNodeModel> {
    constructor() {
        super();
    }

    public get activeColor(): string {
        return this.node().color || '#d3d3d3';
    }

    public outputMapJson: string = '{}';
    public isOutputMapValid: boolean = true;

    protected initializeForm(): FormGroup {
        const form = this.fb.group({});

        const existingOutputMap = this.node().data?.output_map;
        if (existingOutputMap && typeof existingOutputMap === 'object' && Object.keys(existingOutputMap).length > 0) {
            try {
                this.outputMapJson = JSON.stringify(existingOutputMap, null, 2);
            } catch {
                this.outputMapJson = '{}';
            }
        } else {
            this.outputMapJson = '{}';
        }

        return form;
    }

    protected createUpdatedNode(): EndNodeModel {
        let parsedOutputMap: Record<string, unknown> = {};
        try {
            const parsed = JSON.parse(this.outputMapJson);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                parsedOutputMap = parsed as Record<string, unknown>;
            }
        } catch {}

        return {
            ...this.node(),
            data: { output_map: parsedOutputMap },
        };
    }

    public onOutputMapChange(json: string): void {
        this.outputMapJson = json;
    }

    public onOutputMapValidChange(isValid: boolean): void {
        this.isOutputMapValid = isValid;
    }
}
