import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    Injector,
    output,
    signal,
    viewChildren,
} from '@angular/core';

import { isPathUnder } from '../../core/helpers/variable-path.util';

export interface PickerItem {
    tag: string;
    label: string;
    displayLabel: string;
    depth: number;
    fullPath: string;
    /** Listed to keep the variables under it in place, but not offered: another row uses it. */
    disabled?: boolean;
}

let nextPickerId = 0;

@Component({
    selector: 'app-var-picker-flat',
    imports: [],
    template: `
        <div class="vpf-container">
            <!-- mousedown keeps focus in the host's input, so its blur does not close the list before a click lands. -->
            <div
                class="vpf-list"
                role="listbox"
                aria-label="Flow variables"
                [id]="listboxId"
                (mousedown)="$event.preventDefault()"
                (mouseleave)="highlightDefault()"
            >
                @if (hasFilteredItems) {
                    @for (item of filteredItems; track item.fullPath) {
                        <!-- mousemove, not mouseenter: a row scrolled under a still pointer must not take the highlight. -->
                        <button
                            #option
                            type="button"
                            class="vpf-item"
                            role="option"
                            [id]="optionId($index)"
                            [title]="item.fullPath"
                            [style.padding-left.px]="indentPx(item.depth)"
                            [disabled]="item.disabled"
                            [class.vpf-item--highlighted]="$index === highlightedIndex()"
                            [attr.aria-selected]="$index === highlightedIndex()"
                            (mousemove)="highlight($index)"
                            (click)="pathSelected.emit(item.fullPath)"
                        >
                            <span class="vpf-tag">{{ item.tag }}</span>
                            <span class="vpf-label">{{ item.displayLabel }}</span>
                            @if (item.disabled) {
                                <span class="vpf-note">in use</span>
                            }
                        </button>
                    }
                } @else {
                    <div class="vpf-empty">No matching variables</div>
                }
            </div>
        </div>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: [
        `
            .vpf-container {
                background: var(--color-nodes-sidepanel-bg);
                border: 1px solid var(--color-divider-regular);
                border-radius: 4px;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
                width: 280px;
                max-height: 280px;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .vpf-list {
                overflow-y: auto;
                flex: 1;
                padding: 4px;
            }

            .vpf-empty {
                padding: 12px;
                text-align: center;
                color: var(--color-text-secondary);
                font-size: 0.8rem;
            }

            .vpf-item {
                display: flex;
                align-items: center;
                gap: 6px;
                width: 100%;
                text-align: left;
                padding: 5px 8px;
                background: transparent;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                transition: background 0.15s;
                min-width: 0;

                // Hover moves the highlight as well, so only one row is ever lit.
                &.vpf-item--highlighted {
                    background: var(--color-ghost-btn-active);
                }

                &:disabled {
                    cursor: default;
                    opacity: 0.5;
                }
            }

            .vpf-tag {
                flex-shrink: 0;
                font-size: 0.68rem;
                font-weight: 500;
                padding: 1px 5px;
                border-radius: 4px;
                background: rgba(104, 95, 255, 0.25);
                color: rgba(170, 160, 255, 0.9);
                letter-spacing: 0.02em;
                text-transform: lowercase;
            }

            .vpf-label {
                flex: 1;
                min-width: 0;
                font-size: 0.8rem;
                font-family: monospace;
                color: var(--color-text-primary);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .vpf-item--highlighted .vpf-label {
                color: var(--color-text-primary-hover);
            }

            .vpf-note {
                flex-shrink: 0;
                font-size: 0.68rem;
                color: var(--color-text-secondary);
            }
        `,
    ],
})
export class VarPickerFlatComponent {
    private readonly optionButtons = viewChildren<ElementRef<HTMLElement>>('option');

    /** The row Enter picks, as an index into filteredItems; -1 when no row can be picked. */
    protected readonly highlightedIndex = signal(-1);

    /** Unique per picker, for the host input's aria-controls. */
    readonly listboxId = `vpf-${nextPickerId++}`;

    private readonly injector = inject(Injector);
    private allItems: PickerItem[] = [];
    // Whether the user has edited the host's input since the list opened (see highlightDefault).
    private edited = false;
    private currentFilter = '';
    filteredItems: PickerItem[] = [];

    pathSelected = output<string>();

    get hasFilteredItems(): boolean {
        return this.filteredItems.length > 0;
    }

    /** Lists the items as the list opens, filtered by what the host's input holds; nothing is edited yet. */
    setItems(items: PickerItem[], filter: string): void {
        this.allItems = items;
        this.edited = false;
        this.applyFilter(filter);
    }

    /** The highlighted row's path, or null when no row is highlighted. */
    highlightedPath(): string | null {
        return this.filteredItems[this.highlightedIndex()]?.fullPath ?? null;
    }

    /** The highlighted row's element id, for the host input's aria-activedescendant; null for none. */
    activeOptionId(): string | null {
        const index = this.highlightedIndex();
        return index === -1 ? null : this.optionId(index);
    }

    /** Moves the highlight to the next selectable row down (1) or up (-1), wrapping around. */
    moveHighlight(step: 1 | -1): void {
        const count = this.filteredItems.length;
        // With no row highlighted, down starts at the top and up at the bottom.
        let index = this.highlightedIndex() === -1 && step === -1 ? count : this.highlightedIndex();
        for (let tried = 0; tried < count; tried++) {
            index = (index + step + count) % count;
            if (!this.filteredItems[index].disabled) {
                this.highlightedIndex.set(index);
                this.optionButtons()[index]?.nativeElement.scrollIntoView({ block: 'nearest' });
                return;
            }
        }
    }

    indentPx(depth: number): number {
        return Math.min(8 + depth * 12, 80);
    }

    /**
     * Filters by the path in the host's input, e.g. the Input List row's value. `byEdit` is true when
     * the user changed the input (typing, deleting, pasting), false when only its caret moved.
     */
    setFilter(query: string, byEdit: boolean): void {
        if (byEdit) this.edited = true;
        this.applyFilter(query);
    }

    protected optionId(index: number): string {
        return `${this.listboxId}-option-${index}`;
    }

    protected highlight(index: number): void {
        if (!this.filteredItems[index].disabled) this.highlightedIndex.set(index);
    }

    /**
     * The first selectable row is highlighted, as the filter changes or the pointer leaves the list,
     * once the user has edited the input since the list opened and something follows `variables.`,
     * so Enter picks it without an arrow key. Otherwise, e.g. on focus on an untouched `variables.`
     * prefill, or with no row to pick, nothing is: Enter stays the host's (next field, new row), and
     * ArrowDown starts at the top.
     */
    protected highlightDefault(): void {
        const preselect = this.edited && this.currentFilter.trim() !== '';
        this.highlightedIndex.set(preselect ? this.filteredItems.findIndex((item) => !item.disabled) : -1);
    }

    /** Refilters, then scrolls the default highlight into view; the pointer leaving never scrolls. */
    private applyFilter(query: string): void {
        this.currentFilter = query;
        const filter = query.toLowerCase().trim();
        this.filteredItems = filter ? this.filteredBy(filter) : this.allItems;
        this.highlightDefault();
        // The rows for a new filter exist only once it renders, by which time the highlight may have moved.
        afterNextRender(
            () => {
                const index = this.highlightedIndex();
                if (index !== -1) this.optionButtons()[index]?.nativeElement.scrollIntoView({ block: 'nearest' });
            },
            { injector: this.injector }
        );
    }

    /**
     * A filter that starts with a listed path and a `.` or `[` after it, as `user.` or `user.tags[0`,
     * names that path: the list is what lies under it, matched by what follows it, and indented from
     * there. The path itself is typed already, so it is not offered again. Any other filter matches
     * anywhere in a path, as `id` does in `user.id`.
     */
    private filteredBy(filter: string): PickerItem[] {
        const separatorIndex = Math.max(filter.lastIndexOf('.'), filter.lastIndexOf('['));
        const typedPath = filter.slice(0, Math.max(separatorIndex, 0));
        // Several when names differ only in case, as the filter ignores it; each has the same depth.
        const scopes = typedPath ? this.allItems.filter((item) => item.label.toLowerCase() === typedPath) : [];
        if (scopes.length === 0) {
            return this.withParents(this.allItems, (item) => item.fullPath.toLowerCase().includes(filter));
        }
        const rest = filter.slice(separatorIndex);
        const underScopes = this.allItems.filter((item) =>
            scopes.some((scope) => isPathUnder(item.fullPath, scope.fullPath))
        );
        return this.withParents(
            underScopes,
            (item) => item.label.toLowerCase().slice(typedPath.length).includes(rest)
            // At least 0: a key with a dot in its name can make a scope look deeper than what lies under it.
        ).map((item) => ({ ...item, depth: Math.max(0, item.depth - scopes[0].depth - 1) }));
    }

    /**
     * The items that match, each under its parents so a match never shows up indented without them.
     * The items come parents first, as buildVariablePickerItems lists them, though a host may have
     * left some out: parents are told by path, not by depth.
     */
    private withParents(items: PickerItem[], matches: (item: PickerItem) => boolean): PickerItem[] {
        const shown = new Set<PickerItem>();
        const parents: PickerItem[] = [];
        for (const item of items) {
            while (parents.length > 0 && !isPathUnder(item.fullPath, parents[parents.length - 1].fullPath)) {
                parents.pop();
            }
            if (matches(item)) {
                [...parents, item].forEach((shownItem) => shown.add(shownItem));
            }
            parents.push(item);
        }
        return items.filter((item) => shown.has(item));
    }
}
