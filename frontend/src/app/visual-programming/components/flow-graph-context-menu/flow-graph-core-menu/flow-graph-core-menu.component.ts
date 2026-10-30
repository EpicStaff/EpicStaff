import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { MenuNodeType, NODE_MENU_GROUPS, NODE_MENU_LABELS } from '../../../core/constants/node-menu-groups';
import { EDITOR_ACTIONS, EditorAction, EditorActionId } from '../../../core/keymap/editor-actions';
import { formatChord } from '../../../core/keymap/key-chord.util';
import { CreateNodeRequest } from '../../../core/models/node-creation.types';
import { FlowService } from '../../../services/flow.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
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

// A thin space: mac key symbols written side by side (⇧P) run together at the hint's small size.
const MAC_KEY_GAP = '\u2009';

@Component({
    selector: 'app-flow-graph-core-menu',
    template: `
        @for (group of filteredGroups(); track group.title) {
            <section class="menu-group">
                <div class="menu-group__title">{{ group.title }}</div>
                <ul>
                    @for (block of group.blocks; track block.type) {
                        <li
                            [style.border-left-color]="block.color"
                            [class.disabled]="isDisabled(block.type)"
                            [class.note-row]="block.type === NodeType.NOTE"
                        >
                            <div
                                class="block-main"
                                (click)="onBlockClicked(block.type)"
                            >
                                <i
                                    class="node-icon"
                                    [class]="block.icon"
                                    [style.color]="block.color"
                                ></i>
                                <span class="menu-group__item-label">{{ block.label }}</span>
                                @if (block.type === NodeType.NOTE) {
                                    <button
                                        type="button"
                                        class="area-draw-btn"
                                        matTooltip="Place note with selected area"
                                        matTooltipPosition="right"
                                        (click)="$event.stopPropagation(); onAreaNoteClicked()"
                                    >
                                        <i class="ti ti-capture"></i>
                                    </button>
                                }
                                @if (block.keyHint; as keyHint) {
                                    <span class="key-hint">{{ keyHint }}</span>
                                } @else {
                                    <i class="ti ti-plus plus-icon"></i>
                                }
                            </div>
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
                padding: 0;
                border-radius: 8px;
                gap: 0;
                cursor: pointer;
                transition: background 0.2s ease;
                position: relative;
            }

            li:hover {
                background: #2a2a2a;
            }

            /* The main clickable area fills the row except for the area-draw button */
            .block-main {
                display: flex;
                align-items: center;
                gap: 14px;
                flex: 1 1 auto;
                min-width: 0;
                padding: 12px 16px;
            }

            .node-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                font-size: 1.125rem;
            }

            .menu-group__item-label {
                flex: 1 1 auto;
                min-width: 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
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

            .key-hint {
                flex-shrink: 0;
                white-space: nowrap;
                color: var(--color-ks-transparent-text-60);
                font-size: var(--text-body-small-size);
                font-weight: var(--text-body-small-weight);
                line-height: var(--text-body-small-line-height);
                transition: color 0.2s ease;
            }

            li:hover .key-hint {
                color: inherit;
            }

            li.disabled {
                opacity: 0.5;
                cursor: not-allowed;
                pointer-events: none;
            }

            /* Area-draw button shown only on the Note row */
            .area-draw-btn {
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                width: 2.25rem;
                height: 2.25rem;
                margin-right: 0.5rem;
                border-radius: 6px;
                border: none;
                background: transparent;
                color: var(--color-ks-transparent-text-60);
                cursor: pointer;
                font-size: 1rem;
                transition:
                    background 0.2s ease,
                    color 0.2s ease;
                outline: none;
            }

            .area-draw-btn:hover {
                background: #3a3a3a;
                color: var(--color-text-primary, #fff);
            }
        `,
    ],
    imports: [MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowGraphCoreMenuComponent {
    public readonly searchTerm = input('');
    public readonly nodeSelected = output<CreateNodeRequest>();

    readonly NodeType = NodeType;

    protected readonly filteredGroups = computed<FlowGraphMenuGroup[]>(() => {
        const term = this.searchTerm().toLowerCase();
        const keyHints = this.keyHints();
        return NODE_MENU_GROUPS.map((group) => ({
            title: group.title,
            blocks: group.types
                .filter((type) => !this.flowReadOnly.isNodeTypeReadOnly(type))
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
                keyHints.set(type, formatChord(chord, this.keymap.isMac).join(this.keymap.isMac ? MAC_KEY_GAP : '+'));
            }
        });
        return keyHints;
    });

    private readonly keymap = inject(KeymapService);
    private readonly flowService = inject(FlowService);
    private readonly flowReadOnly = inject(FlowReadOnlyService);

    protected onBlockClicked(type: NodeType): void {
        this.nodeSelected.emit({ type });
    }

    protected onAreaNoteClicked(): void {
        this.nodeSelected.emit({ type: NodeType.NOTE, areaSelection: true });
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
