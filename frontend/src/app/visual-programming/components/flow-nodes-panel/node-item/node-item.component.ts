import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { FExternalItemDirective, FExternalItemPlaceholderDirective, FExternalItemPreviewDirective } from '@foblex/flow';

import { NODE_COLORS, NODE_ICONS } from '../../../core/enums/node-config';
import { NodeType } from '../../../core/enums/node-type';
import {
    AgentNodeModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    TaskNodeModel,
    ToolNodeModel,
} from '../../../core/models/node.model';
import { NodePreviewComponent } from './node-preview/node-preview.component';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-node-item',
    standalone: true,
    imports: [
        CommonModule,
        FExternalItemDirective,
        FExternalItemPlaceholderDirective,
        FExternalItemPreviewDirective,
        NodePreviewComponent,
        AppSvgIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <button
            class="node-item"
            [attr.data-node-type]="node.type"
            type="button"
            [attr.aria-label]="'Add ' + node.node_name"
            fExternalItem
            [fData]="node"
            [fPreviewMatchSize]="false"
        >
            <div class="node-icon" [style.--node-color]="getNodeColor(node.type)">
                <i [class]="getNodeIcon(node.type)"></i>
            </div>
            <div class="node-info">
                <div class="node-name">
                    {{ getNodeDisplayName() }}
                </div>
                <div class="node-details">
                    <div class="node-description" *ngIf="node.node_name">
                        {{ node.node_name }}
                    </div>
                </div>
            </div>
            <div class="hover-arrow">
                <app-svg-icon icon="arrow-right" size="18px"></app-svg-icon>
            </div>

            <!-- Preview element while dragging (using separate component) -->
            <app-node-preview *fExternalItemPreview [node]="node"></app-node-preview>

            <!-- Placeholder on the original location -->
            <div class="node-item-placeholder" *fExternalItemPlaceholder>
                <div class="node-icon" [style.--node-color]="getNodeColor(node.type)">
                    <i [class]="getNodeIcon(node.type)"></i>
                </div>
                <div class="node-name">Drop to add</div>
            </div>
        </button>
    `,
    styles: [
        `
            .node-item {
                display: flex;
                align-items: center;
                padding: 10px 10px;
                height: 56px;
                width: 100%;
                cursor: pointer;
                transition: all 0.2s ease;
                background-color: var(--gray-850, #121212);
                border-radius: 6px;
                border: none;
                text-align: left;
                position: relative;
                overflow: hidden;

                &:hover {
                    background-color: var(--gray-800, #1a1a1a);
                    border-color: var(--gray-700, #333);

                    .node-icon {
                        filter: brightness(1.2);
                    }

                    .show-in-canvas {
                        opacity: 1;
                    }

                    .hover-arrow {
                        transform: translateX(0);
                        opacity: 1;
                    }
                }

                &:focus-visible {
                    outline: 2px solid var(--accent-color, #685fff);
                    outline-offset: 2px;
                }

                .node-icon {
                    min-width: 32px;
                    width: 32px;
                    height: 32px;
                    background-color: color-mix(in srgb, var(--node-color) 15%, transparent);
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin-right: 10px;
                    color: var(--node-color);
                    transition: all 0.2s ease;

                    i {
                        font-size: 16px;
                        transition: all 0.2s ease;
                    }
                }

                .node-info {
                    display: flex;
                    flex-direction: column;
                    flex: 1;
                    gap: 5px;
                    overflow: hidden;

                    .node-name {
                        color: var(--white, #fff);
                        font-size: 13px;
                        font-weight: 500;
                    }

                    .node-details {
                        display: flex;
                        flex-direction: column;
                        gap: 0;

                        .node-description {
                            color: var(--gray-400, #b4b4b4);
                            font-size: 11px;
                            line-height: 1.3;
                            overflow: hidden;
                            text-overflow: ellipsis;
                            white-space: nowrap;
                        }
                    }
                }

                .hover-arrow {
                    position: absolute;
                    right: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: var(--accent-color, #685fff);
                    transform: translateX(20px);
                    opacity: 0;
                    transition: all 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275);

                    app-svg-icon {
                        font-size: 18px;
                    }
                }
            }

            .node-item-placeholder {
                display: flex;
                align-items: center;
                padding: 8px;
                height: 56px;
                background-color: var(--gray-850, #1a1a1a);
                border-radius: 6px;
                opacity: 0.5;
                gap: 8px;

                .node-name {
                    color: var(--white, #fff);
                    font-size: 13px;
                    font-weight: 500;
                    font-style: italic;
                }
            }
        `,
    ],
})
export class NodeItemComponent {
    @Input() public node!: NodeModel;
    @Output() public nodeClicked = new EventEmitter<NodeModel>();

    private readonly nodeColors = NODE_COLORS;
    private readonly nodeIcons = NODE_ICONS;

    public getNodeColor(type: NodeType): string {
        return this.node.color || this.nodeColors[type] || '#685fff';
    }

    public getNodeIcon(type: NodeType): string {
        return this.node.icon || this.nodeIcons[type] || 'ti ti-code';
    }

    public getNodeDisplayName(): string {
        if (!this.node) {
            return 'Unknown Node';
        }

        switch (this.node.type) {
            case NodeType.START:
                return 'Start';
            case NodeType.AGENT:
                return (this.node as AgentNodeModel).data?.role || this.node.node_name;
            case NodeType.PROJECT:
                return (this.node as ProjectNodeModel).data?.name || this.node.node_name;
            case NodeType.TASK:
                return (this.node as TaskNodeModel).data?.name || this.node.node_name;
            case NodeType.PYTHON:
                return (this.node as PythonNodeModel).data?.name || this.node.node_name;
            case NodeType.TOOL:
                return (this.node as ToolNodeModel).data?.name || this.node.node_name;
            case NodeType.LLM:
                return (this.node as LLMNodeModel).data?.custom_name || this.node.node_name;

            default:
                return this.node.node_name;
        }
    }
}
