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
    public readonly searchTerm = input('');
    public readonly nodeSelected = output<NodeType>();

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
            label: 'Code Agent',
            type: NodeType.CODE_AGENT,
            icon: NODE_ICONS[NodeType.CODE_AGENT],
            color: NODE_COLORS[NodeType.CODE_AGENT],
        },
    ];

    private readonly flowService = inject(FlowService);

    public onBlockClicked(type: NodeType): void {
        this.nodeSelected.emit(type);
    }

    public isDisabled(type: NodeType): boolean {
        if (type === NodeType.END) {
            return this.flowService.hasEndNode();
        }
        return false;
    }
}
