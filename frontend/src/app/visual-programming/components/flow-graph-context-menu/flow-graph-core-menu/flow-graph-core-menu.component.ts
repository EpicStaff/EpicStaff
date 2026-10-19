import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { MenuNodeType, NODE_MENU_GROUPS, NODE_MENU_LABELS } from '../../../core/constants/node-menu-groups';
import { EDITOR_ACTIONS, EditorAction, EditorActionId } from '../../../core/keymap/editor-actions';
import { formatChord } from '../../../core/keymap/key-chord.util';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';
import { FlowService } from '../../../services/flow.service';
import { KeymapService } from '../../../services/keymap.service';

interface FlowGraphBlock {
    label: string;
    type: NodeType;
    icon: string;
    color: string;
    keyHint: string | null;
}

interface FlowGraphMenuGroup {
    title: string;
    blocks: FlowGraphBlock[];
}

const NODE_ACTION_BY_TYPE: ReadonlyMap<NodeType, EditorActionId> = new Map(
    EDITOR_ACTIONS.flatMap((action: EditorAction) =>
        action.nodeType && !action.param ? [[action.nodeType, action.id] as const] : []
    )
);

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
                                class="node-icon"
                                [class]="block.icon"
                                [style.color]="block.color"
                            ></i>
                            <span class="menu-group__item-label">{{ block.label }}</span>
                            @if (block.keyHint; as keyHint) {
                                <span class="key-hint">{{ keyHint }}</span>
                            } @else {
                                <i class="ti ti-plus plus-icon"></i>
                            }
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
                --row-gap: 14px;
                gap: var(--row-gap);
                cursor: pointer;
                transition: background 0.2s ease;
                position: relative;
            }

            .node-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                font-size: 1.125rem;
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

            .menu-group__item-label {
                flex: 1 1 auto;
                min-width: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            .key-hint {
                flex-shrink: 0;
                max-width: 0;
                margin-left: calc(-1 * var(--row-gap));
                overflow: hidden;
                white-space: nowrap;
                color: var(--color-ks-transparent-text-60);
                font-size: var(--text-body-small-size);
                font-weight: var(--text-body-small-weight);
                line-height: var(--text-body-small-line-height);
                opacity: 0;
                transition:
                    opacity 0.2s ease,
                    max-width 0s linear 0.2s,
                    margin-left 0s linear 0.2s;
            }

            li:hover .key-hint {
                opacity: 1;
                max-width: 12em;
                margin-left: 0;
                transition: opacity 0.2s ease;
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
        const keyHints = this.keyHints();
        return NODE_MENU_GROUPS.map((group) => ({
            title: group.title,
            blocks: group.types
                .map((type) => toBlock(type, keyHints.get(type) ?? null))
                .filter((block) => block.label.toLowerCase().includes(term)),
        })).filter((group) => group.blocks.length > 0);
    });

    private readonly keyHints = computed(() => {
        const bindings = this.keymap.bindings();
        const keyHints = new Map<NodeType, string>();
        NODE_ACTION_BY_TYPE.forEach((actionId, type) => {
            const [chord] = bindings.get(actionId) ?? [];
            if (chord) {
                keyHints.set(type, formatChord(chord, this.keymap.isMac).join(this.keymap.isMac ? '' : '+'));
            }
        });
        return keyHints;
    });

    private readonly keymap = inject(KeymapService);
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

function toBlock(type: MenuNodeType, keyHint: string | null): FlowGraphBlock {
    return {
        label: NODE_MENU_LABELS[type],
        type,
        icon: NODE_ICONS[type],
        color: NODE_COLORS[type],
        keyHint,
    };
}
