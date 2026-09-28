import { ChangeDetectionStrategy, Component, ElementRef, output, signal, viewChildren } from '@angular/core';

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
                (mouseleave)="highlightedIndex.set(-1)"
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

    /** The row Enter picks, as an index into filteredItems; -1 for none. */
    protected readonly highlightedIndex = signal(-1);

    /** Unique per picker, for the host input's aria-controls. */
    readonly listboxId = `vpf-${nextPickerId++}`;

    private allItems: PickerItem[] = [];
    filteredItems: PickerItem[] = [];

    pathSelected = output<string>();

    get hasFilteredItems(): boolean {
        return this.filteredItems.length > 0;
    }

    setItems(items: PickerItem[]): void {
        this.allItems = items;
        this.filteredItems = items;
        this.highlightedIndex.set(-1);
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

    /** Filters by the path typed in the host's input, e.g. the Input List row's value. */
    setFilter(query: string): void {
        this.applyFilter(query);
    }

    protected optionId(index: number): string {
        return `${this.listboxId}-option-${index}`;
    }

    protected highlight(index: number): void {
        if (!this.filteredItems[index].disabled) this.highlightedIndex.set(index);
    }

    /**
     * Keeps the items whose path matches, each under its parents so a match never shows up
     * indented without them. The items come parents first, as buildVariablePickerItems lists them,
     * though a host may have left some out: parents are told by path, not by depth.
     */
    private applyFilter(query: string): void {
        this.highlightedIndex.set(-1);
        const filter = query.toLowerCase().trim();
        if (!filter) {
            this.filteredItems = this.allItems;
            return;
        }
        const shown = new Set<PickerItem>();
        const parents: PickerItem[] = [];
        for (const item of this.allItems) {
            while (parents.length > 0 && !isPathUnder(item.fullPath, parents[parents.length - 1].fullPath)) {
                parents.pop();
            }
            if (item.fullPath.toLowerCase().includes(filter)) {
                [...parents, item].forEach((shownItem) => shown.add(shownItem));
            }
            parents.push(item);
        }
        this.filteredItems = this.allItems.filter((item) => shown.has(item));
    }
}
