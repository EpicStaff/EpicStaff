import {
    ChangeDetectionStrategy,
    Component,
    Input,
} from '@angular/core';
import { NgFor, NgIf, NgStyle } from '@angular/common';

import {
    BaseNodeModel,
    NodeModel,
} from '../../core/models/node.model';

@Component({
    standalone: true,
    selector: 'app-flow-node-variables-overlay',
    template: `
        @if (showInputsOverlay) {
            <div
                class="inputs-overlay"
                [ngStyle]="{ '--node-overlay-color': node.color || '#23272e' }"
            >
                <div class="inputs-title">Inputs</div>
                <div class="inputs-list">
                    @for (key of inputKeys; track key) {
                        <div class="input-item">
                            <span class="input-key" [title]="key">{{ key }}</span>
                            <span class="equals-sign">=</span>
                            <span
                                class="input-value"
                                [title]="baseNode?.input_map?.[key] ?? ''"
                            >
                                {{ baseNode?.input_map?.[key] }}
                            </span>
                        </div>
                    }
                </div>
            </div>
        }

        @if (showOutputOverlay) {
            <div
                class="output-overlay"
                [ngStyle]="{ '--node-overlay-color': node.color || '#23272e' }"
            >
                <div class="output-title">Output</div>
                <span class="output-label">
                    {{ baseNode?.output_variable_path }}
                </span>
            </div>
        }
    `,
    styleUrls: ['./flow-node-variables-overlay.component.scss'],
    imports: [NgIf, NgFor, NgStyle],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowNodeVariablesOverlayComponent {
    @Input({ required: true }) node!: NodeModel;
    @Input() showVariables = false;

    public get baseNode(): (BaseNodeModel & NodeModel) | null {
        const node = this.node;
        return this.isBaseNode(node) ? node : null;
    }

    public get inputKeys(): string[] {
        if (!this.baseNode?.input_map) {
            return [];
        }

        return Object.keys(this.baseNode.input_map);
    }

    public get showInputsOverlay(): boolean {
        return (
            this.showVariables &&
            !!this.baseNode &&
            this.inputKeys.length > 0
        );
    }

    public get showOutputOverlay(): boolean {
        return (
            this.showVariables &&
            !!this.baseNode &&
            !!this.baseNode.output_variable_path
        );
    }

    private isBaseNode(
        node: NodeModel | null | undefined
    ): node is BaseNodeModel & NodeModel {
        return !!node && 'input_map' in node && 'output_variable_path' in node;
    }
}

