import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { MenuNodeType, NODE_MENU_GROUPS, NODE_MENU_LABELS } from '../../../core/constants/node-menu-groups';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';
import { FlowService } from '../../../services/flow.service';

interface FlowGraphBlock {
    label: string;
    type: NodeType;
    icon: string;
    color: string;
}

interface FlowGraphMenuGroup {
    title: string;
    blocks: FlowGraphBlock[];
}

@Component({
    selector: 'app-flow-graph-core-menu',
    template: `
        @for (group of filteredGroups(); track group.title) {
            <section class="menu-group">
                <div class="menu-group__title">{{ group.title }}</div>
                <ul>
                    @for (block of group.blocks; track block.type) {
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
            </section>
        }
    `,
    styles: [
        `
            .menu-group__title {
                padding: 12px 16px 4px;
                color: var(--color-ks-transparent-text-60);
                font-size: var(--text-body-small-large-size);
                font-weight: var(--text-body-small-large-weight);
                line-height: var(--text-body-small-large-line-height);
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }

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
    public readonly nodeSelected = output<CreateNodeRequest>();

    protected readonly filteredGroups = computed<FlowGraphMenuGroup[]>(() => {
        const term = this.searchTerm().toLowerCase();
        return NODE_MENU_GROUPS.map((group) => ({
            title: group.title,
            blocks: group.types.map(toBlock).filter((block) => block.label.toLowerCase().includes(term)),
        })).filter((group) => group.blocks.length > 0);
    });

    private readonly flowService = inject(FlowService);

    protected onBlockClicked(type: NodeType): void {
        this.nodeSelected.emit({ type });
    }

    protected isDisabled(type: NodeType): boolean {
        if (type === NodeType.END) {
            return this.flowService.hasEndNode();
        }

        return false;
    }
}

function toBlock(type: MenuNodeType): FlowGraphBlock {
    return {
        label: NODE_MENU_LABELS[type],
        type,
        icon: NODE_ICONS[type],
        color: NODE_COLORS[type],
    };
}
