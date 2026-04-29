import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
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

@Component({
    selector: 'app-search-node-item',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="search-node-item"
            (click)="onNodeClick()"
            (dblclick)="onNodeDoubleClick($event)"
        >
            <div
                class="node-icon"
                [style.--node-color]="getNodeColor(node.type)"
            >
                <i [class]="getNodeIcon(node.type)"></i>
            </div>
            <div class="node-info">
                <div class="node-name">
                    {{ getNodeDisplayName() }}
                </div>
                <div class="node-details">
                    <div
                        class="node-description"
                        *ngIf="node.node_name"
                    >
                        {{ node.node_name }}
                    </div>
                </div>
            </div>
            <div class="show-in-canvas">
                <app-svg-icon
                    icon="eye-search"
                    size="16px"
                ></app-svg-icon>
            </div>
        </div>
    `,
    styles: [
        `
            .search-node-item {
                display: flex;
                align-items: center;
                padding: 10px 10px;
                height: 56px;
                width: 100%;
                cursor: pointer;
                transition: all 0.2s ease;
                background-color: var(--gray-850, #121212);
                border-radius: 6px;
                border: 1px solid transparent;
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

                .show-in-canvas {
                    position: absolute;
                    right: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: var(--accent-color, #685fff);
                    opacity: 0; /* Hidden by default, only shown on hover */
                    transition: opacity 0.2s ease;
                    background-color: rgba(104, 95, 255, 0.1);
                    width: 28px;
                    height: 28px;
                    border-radius: 4px;

                    i {
                        font-size: 16px;
                    }
                }
            }
        `,
    ],
})
export class SearchNodeItemComponent {
    @Input() public node!: NodeModel;
    @Output() public nodeSelected = new EventEmitter<NodeModel>();
    @Output() public nodeDoubleClicked = new EventEmitter<{
        node: NodeModel;
        event: MouseEvent;
    }>();

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

    public onNodeClick(): void {
        this.nodeSelected.emit(this.node);
    }

    public onNodeDoubleClick(event: MouseEvent): void {
        event.stopPropagation();
        this.nodeDoubleClicked.emit({ node: this.node, event });
    }
}
