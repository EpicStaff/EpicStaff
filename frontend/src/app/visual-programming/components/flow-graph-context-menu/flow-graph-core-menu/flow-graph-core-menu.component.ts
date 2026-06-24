import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';

import { NODE_COLORS, NODE_ICONS } from '../../../core/enums/node-config';
import { NodeType } from '../../../core/enums/node-type';
import { FlowService } from '../../../services/flow.service';

interface FlowGraphBlock {
    label: string;
    type: NodeType;
    icon: string;
    color: string;
}

@Component({
    selector: 'app-flow-graph-core-menu',
    standalone: true,
    template: `
        <ul>
            @for (block of filteredBlocks(); track block.type) {
                <li
                    (click)="onBlockClicked(block.type)"
                    [style.border-left-color]="block.color"
                    [class.disabled]="isDisabled(block.type)"
                >
                    <i
                        [class]="block.icon"
                        [style.color]="block.color"
                    ></i>
                    {{ block.label }}
                    <i class="ti ti-plus plus-icon"></i>
                </li>
            }
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

            .node-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }

            .node-label {
                color: #fff;
            }

            li:hover {
                background: #2a2a2a;
            }

            .plus-icon {
                margin-left: auto;
                color: #bbb;
                opacity: 0;
                transition:
                    opacity 0.2s ease,
                    color 0.2s ease;
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
})
export class FlowGraphCoreMenuComponent {
    private readonly flowService = inject(FlowService);

    public readonly searchTerm = input('');
    public readonly nodeSelected = output<{ type: NodeType; data: unknown }>();

    public readonly filteredBlocks = computed(() =>
        this.blocks.filter((block) => block.label.toLowerCase().includes(this.searchTerm().toLowerCase()))
    );

    public readonly blocks: FlowGraphBlock[] = [
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
            label: 'Audio to text',
            type: NodeType.AUDIO_TO_TEXT,
            icon: NODE_ICONS[NodeType.AUDIO_TO_TEXT],
            color: NODE_COLORS[NodeType.AUDIO_TO_TEXT],
        },
        {
            label: 'End',
            type: NodeType.END,
            icon: NODE_ICONS[NodeType.END],
            color: NODE_COLORS[NodeType.END],
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
            label: 'Classification Decision Table',
            type: NodeType.CLASSIFICATION_TABLE,
            icon: NODE_ICONS[NodeType.CLASSIFICATION_TABLE],
            color: NODE_COLORS[NodeType.CLASSIFICATION_TABLE],
        },
        {
            label: 'Webhook Trigger',
            type: NodeType.WEBHOOK_TRIGGER,
            icon: NODE_ICONS[NodeType.WEBHOOK_TRIGGER],
            color: NODE_COLORS[NodeType.WEBHOOK_TRIGGER],
        },
        {
            label: 'Telegram Trigger',
            type: NodeType.TELEGRAM_TRIGGER,
            icon: NODE_ICONS[NodeType.TELEGRAM_TRIGGER],
            color: NODE_COLORS[NodeType.TELEGRAM_TRIGGER],
        },
        {
            label: 'Schedule Trigger',
            type: NodeType.SCHEDULE_TRIGGER,
            icon: NODE_ICONS[NodeType.SCHEDULE_TRIGGER],
            color: NODE_COLORS[NodeType.SCHEDULE_TRIGGER],
        },
        {
            label: 'Code Agent',
            type: NodeType.CODE_AGENT,
            icon: NODE_ICONS[NodeType.CODE_AGENT],
            color: NODE_COLORS[NodeType.CODE_AGENT],
        },
    ];

    public onBlockClicked(type: NodeType): void {
        let data: unknown = null;

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
                        },
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
            data = null;
        } else if (type === NodeType.AUDIO_TO_TEXT) {
            data = null;
        } else if (type === NodeType.WEBHOOK_TRIGGER) {
            data = {
                webhook_trigger: null,
                python_code: {
                    name: 'Webhook trigger Node',
                    libraries: [],
                    code: 'def main(trigger_payload: dict, **kwargs: dict) -> dict:\n    """\n    Main handler for processing webhook-triggered events.\n\n    Parameters\n    ----------\n    trigger_payload : dict\n        The data received from a third-party service via a webhook.\n    **kwargs : dict\n        Additional domain variables passed to the function.\n\n    Returns\n    -------\n    dict\n        A dictionary containing the updated values for domain variables.\n        The returned structure must include all changes that should be\n        applied to the domain.\n    """\n    return {\n        "new_data": trigger_payload,\n    }\n',
                    entrypoint: 'main',
                },
            };
        } else if (type === NodeType.TELEGRAM_TRIGGER) {
            data = {
                webhook_trigger: null,
                telegram_bot_api_key: '',
                fields: [],
            };
        } else if (type === NodeType.SCHEDULE_TRIGGER) {
            data = null;
        } else if (type === NodeType.END) {
            data = null;
        }

        this.nodeSelected.emit({ type, data });
    }

    public isDisabled(type: NodeType): boolean {
        if (type === NodeType.END) {
            return this.flowService.hasEndNode();
        }

        return false;
    }
}
