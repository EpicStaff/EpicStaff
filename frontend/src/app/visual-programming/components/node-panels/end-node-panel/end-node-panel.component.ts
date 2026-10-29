import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { JsonEditorComponent } from '@shared/components';

import { CODE_DIFF_HINT_EXPAND_PANEL } from '../../../core/constants/code-diff-hints';
import { EndNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { NODE_PANEL_DIFF } from '../../../core/providers/node-panel-diff.token';
import { jsonChangeFor } from '../../../utils/diff';
import { CodeDiffViewComponent } from '../../code-diff-view/code-diff-view.component';
import { DiffFieldMarkComponent } from '../../diff-field-mark/diff-field-mark.component';

@Component({
    selector: 'app-end-node-panel',
    imports: [ReactiveFormsModule, JsonEditorComponent, DiffFieldMarkComponent, CodeDiffViewComponent],
    template: `
        <div class="panel-container">
            <div class="panel-content">
                <div
                    class="form-container"
                    [class.form-container--diff]="outputMapDiff()"
                >
                    <!-- Output Map Title -->
                    <div class="output-map-container">
                        <div class="label-container">
                            <label>Output Map</label>
                        </div>
                        @if (outputMapDiff(); as outputMap) {
                            <app-code-diff-view
                                class="output-map-diff"
                                language="json"
                                [current]="outputMap.current"
                                [version]="outputMap.version"
                            />
                        } @else {
                            <!-- The mark shows only in the narrow panel: the widened one shows the diff above instead. -->
                            <app-diff-field-mark
                                [diffField]="'output_map'"
                                [diffHint]="outputMapDiffHint"
                                [diffDrawsBadge]="true"
                            >
                                <app-json-editor
                                    class="json-editor"
                                    [jsonData]="outputMapJson"
                                    [readonly]="isReadOnly()"
                                    [fullHeight]="false"
                                    (jsonChange)="onOutputMapChange($event)"
                                    (validationChange)="onOutputMapValidChange($event)"
                                ></app-json-editor>
                            </app-diff-field-mark>
                        }
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
                font-size: 0.875rem;
                color: var(--color-text-secondary);
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

            // The diff of the widened panel fills the panel's height (Monaco needs a sized box).
            .form-container--diff {
                flex: 1;
                min-height: 0;

                .output-map-container {
                    flex: 1;
                    min-height: 0;
                }
            }

            .output-map-diff {
                min-height: 300px;
                border: 1px solid var(--color-divider-subtle);
                border-radius: 4px;
                overflow: hidden;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EndNodePanelComponent extends BaseSidePanel<EndNodeModel> {
    /**
     * Changes tab of a version preview, widened panel: the changed output map, shown as a diff of its JSON. The
     * narrow panel's editor gets the field mark instead, with a hint where to see the changes.
     */
    protected readonly outputMapDiff = computed(() =>
        this.isExpanded() ? jsonChangeFor(this.panelDiff(), 'output_map') : null
    );
    protected readonly outputMapDiffHint = CODE_DIFF_HINT_EXPAND_PANEL;

    private readonly panelDiff = inject(NODE_PANEL_DIFF);

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
        this.notifyExternalChange();
    }

    public onOutputMapValidChange(isValid: boolean): void {
        this.isOutputMapValid = isValid;
    }
}
