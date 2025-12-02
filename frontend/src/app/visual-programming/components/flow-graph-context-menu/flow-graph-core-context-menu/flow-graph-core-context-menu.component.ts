import {
    Component,
    Input,
    ChangeDetectionStrategy,
    Output,
    EventEmitter,
} from '@angular/core';
import { NgFor } from '@angular/common';
import { NodeType } from '../../../core/enums/node-type';
import { NODE_COLORS, NODE_ICONS } from '../../../core/enums/node-config';
import { inject } from '@angular/core';
import { FlowService } from '../../../services/flow.service';

interface FlowGraphBlock {
    label: string;
    type: NodeType;
    icon: string;
    color: string;
}

@Component({
    selector: 'app-flow-graph-core-context-menu',
    standalone: true,
    template: `
        <ul>
            <li
                *ngFor="let block of filteredBlocks"
                (click)="onBlockClicked(block.type)"
                [style.border-left-color]="block.color"
                [class.disabled]="isDisabled(block.type)"
            >
                <i [class]="block.icon" [style.color]="block.color"></i>
                {{ block.label }}
                <i class="ti ti-plus plus-icon"></i>
            </li>
        </ul>
    `,
    styles: [
        `
            ul {
                list-style: none;
                padding: 0 16px;
                margin: 0;
            }
            li {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 16px;
                border-radius: 8px;
                gap: 14px;
                cursor: pointer;
                transition: background 0.2s ease;
                position: relative;
            }
            li:hover {
                background: #2a2a2a;
            }
            li i {
                font-size: 16px;
                color: #bbb; /* Fallback color */
                transition: color 0.2s ease;
            }
            li:hover i {
                color: inher;
            }
            .plus-icon {
                margin-left: auto;
                font-size: 18px;
                color: #bbb;
                opacity: 0;
                transition: opacity 0.2s ease, color 0.2s ease;
            }
            li:hover .plus-icon {
                opacity: 1;
                color: inherit;
            }
            li.disabled {
                opacity: 0.5;
                cursor: not-allowed;
                pointer-events: none;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [NgFor],
})
export class FlowGraphCoreContextMenuComponent {
    @Input() public searchTerm: string = '';

    @Output() public nodeSelected: EventEmitter<{
        type: NodeType;
        data: any;
    }> = new EventEmitter();

    private flowService = inject(FlowService);

    // Use NodeType-based mappings for icon & color
    public blocks: FlowGraphBlock[] = [
        {
            label: 'Python Code Node',
            type: NodeType.PYTHON,
            icon: NODE_ICONS[NodeType.PYTHON],
            color: NODE_COLORS[NodeType.PYTHON],
        },
        {
            label: 'File Extractor',
            type: NodeType.FILE_EXTRACTOR,
            icon: NODE_ICONS[NodeType.FILE_EXTRACTOR],
            color: NODE_COLORS[NodeType.FILE_EXTRACTOR],
        },
        {
            label: 'End',
            type: NodeType.END,
            icon: NODE_ICONS[NodeType.END],
            color: NODE_COLORS[NodeType.END],
        },
        {
            label: 'Conditional Edge',
            type: NodeType.EDGE,
            icon: NODE_ICONS[NodeType.EDGE],
            color: NODE_COLORS[NodeType.EDGE],
        },
        {
            label: 'Group',
            type: NodeType.GROUP,
            icon: NODE_ICONS[NodeType.GROUP],
            color: '#ffffff',
        },
        {
            label: 'Note',
            type: NodeType.NOTE,
            icon: NODE_ICONS[NodeType.NOTE],
            color: NODE_COLORS[NodeType.NOTE],
        },
        {
            label: 'Decision Table',
            type: NodeType.TABLE,
            icon: NODE_ICONS[NodeType.TABLE],
            color: NODE_COLORS[NodeType.TABLE],
        },
        {
            label: 'Webhook Trigger',
            type: NodeType.WEBHOOK_TRIGGER,
            icon: NODE_ICONS[NodeType.WEBHOOK_TRIGGER],
            color: NODE_COLORS[NodeType.WEBHOOK_TRIGGER],
        },
        // {
        //   label: 'Decision Table',
        //   type: NodeType.TABLE,
        //   icon: NODE_ICONS[NodeType.TABLE],
        //   color: NODE_COLORS[NodeType.TABLE],
        // },
    ];

    public get filteredBlocks(): FlowGraphBlock[] {
        return this.blocks.filter((block) =>
            block.label.toLowerCase().includes(this.searchTerm.toLowerCase())
        );
    }

    public onBlockClicked(type: NodeType): void {
        let data: any = null;

        if (type === NodeType.EDGE) {
            data = {
                source: null,
                then: null,
                python_code: {
                    libraries: [],
                    code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
                    entrypoint: 'main',
                },
            };
        } else if (type === NodeType.PYTHON) {
            data = {
                name: 'Python Code Node',
                libraries: [],
                code: 'def main(arg1: str, arg2: str) -> dict:\n    return {\n        "result": arg1 + arg2,\n    }\n',
                entrypoint: 'main',
            };
        } else if (type === NodeType.GROUP) {
            data = 'group'; // Assign "group" if NodeType is GROUP
        } else if (type === NodeType.TABLE) {
            data = {
                name: 'Decision Table',
                table: {
                    graph: null,
                    condition_groups: [
                        {
                            group_name: 'Group 1',
                            group_type: 'complex',
                            expression: null,
                            conditions: [],
                            manipulation: null,
                            next_node: null,
                            order: 1,
                            valid: false,
                        }
                    ],
                    node_name: '',
                    default_next_node: null,
                    next_error_node: null,
                },
            };
        } else if (type === NodeType.NOTE) {
            data = {
                content: 'Add your note here...',
                backgroundColor: NODE_COLORS[NodeType.NOTE],
            };
        } else if (type === NodeType.FILE_EXTRACTOR) {
            data = null; // File extractor data is unknown as specified
        }
        else if (type === NodeType.WEBHOOK_TRIGGER) {
            data = {
                webhook_trigger: 0,
                python_code: {
                    name: 'Webhook trigger Node',
                    libraries: [],
                    code: 'def main(trigger_payload: dict, **kwargs: dict) -> dict:\n    """\n    Main handler for processing webhook-triggered events.\n\n    Parameters\n    ----------\n    trigger_payload : dict\n        The data received from a third-party service via a webhook.\n    **kwargs : dict\n        Additional domain variables passed to the function.\n\n    Returns\n    -------\n    dict\n        A dictionary containing the updated values for domain variables.\n        The returned structure must include all changes that should be\n        applied to the domain.\n    """\n    return {\n        "new_data": trigger_payload,\n    }\n',
                    entrypoint: 'main',
                }
            };
        } else if (type === NodeType.END) {
            data = null; // End node data is unknown as specified
        }

        this.nodeSelected.emit({ type, data });
    }

    public isDisabled(type: NodeType): boolean {
        if (type === NodeType.END) {
            return this.flowService.hasEndNode();
        }
        if (type === NodeType.GROUP) {
            return true;
        }
        return false;
    }
}
