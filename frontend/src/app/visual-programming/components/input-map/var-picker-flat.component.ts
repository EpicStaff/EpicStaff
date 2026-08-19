import { CommonModule } from '@angular/common';
import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, Input, output, ViewChild } from '@angular/core';

export interface PickerItem {
    tag: string;
    label: string;
    displayLabel: string;
    depth: number;
    fullPath: string;
}

@Component({
    selector: 'app-var-picker-flat',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="vpf-container">
            <div class="vpf-search">
                <input
                    #searchInput
                    type="text"
                    placeholder="Search variables..."
                    autocomplete="off"
                    (input)="onSearchInput($event)"
                    (keydown)="$event.stopPropagation()"
                />
            </div>
            <div class="vpf-list">
                @if (hasFilteredItems) {
                    @for (item of filteredItems; track item.fullPath) {
                        <button
                            type="button"
                            class="vpf-item"
                            [title]="item.fullPath"
                            [style.padding-left.px]="indentPx(item.depth)"
                            (click)="pathSelected.emit(item.fullPath)"
                        >
                            <span class="vpf-tag">{{ item.tag }}</span>
                            <span class="vpf-label">{{ item.displayLabel }}</span>
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
                border-radius: 6px;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
                width: 280px;
                max-height: 280px;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .vpf-search {
                padding: 8px;
                border-bottom: 1px solid var(--color-divider-subtle);

                input {
                    width: 100%;
                    box-sizing: border-box;
                    padding: 6px 10px;
                    background: var(--color-input-background);
                    border: 1px solid var(--color-input-border);
                    border-radius: 4px;
                    color: var(--color-text-primary);
                    font-size: 0.8rem;
                    outline: none;
                    transition: border-color 0.15s;

                    &:focus {
                        border-color: var(--accent-color);
                    }
                    &::placeholder {
                        color: var(--color-input-text-placeholder);
                    }
                }
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

                &:hover {
                    background: var(--color-ghost-btn-active);
                }
            }

            .vpf-tag {
                flex-shrink: 0;
                font-size: 0.68rem;
                font-weight: 600;
                padding: 1px 5px;
                border-radius: 3px;
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

            .vpf-item:hover .vpf-label {
                color: var(--color-text-primary-hover);
            }
        `,
    ],
})
export class VarPickerFlatComponent implements AfterViewInit {
    @ViewChild('searchInput') private searchInputRef!: ElementRef<HTMLInputElement>;

    @Input() autofocusSearch = true;

    private allItems: PickerItem[] = [];
    filteredItems: PickerItem[] = [];

    pathSelected = output<string>();

    ngAfterViewInit(): void {
        if (this.autofocusSearch) {
            this.searchInputRef.nativeElement.focus();
        }
    }

    get hasFilteredItems(): boolean {
        return this.filteredItems.length > 0;
    }

    setItems(items: PickerItem[]): void {
        this.allItems = items;
        this.filteredItems = items;
    }

    indentPx(depth: number): number {
        return Math.min(8 + depth * 12, 80);
    }

    onSearchInput(event: Event): void {
        const query = (event.target as HTMLInputElement).value;
        this.applyFilter(query);
    }

    /**
     * Applies a filter query coming from an external source (e.g. the input-map row's
     * value input) and keeps the picker's own search field in sync with it.
     */
    setFilter(query: string): void {
        if (this.searchInputRef) {
            this.searchInputRef.nativeElement.value = query;
        }
        this.applyFilter(query);
    }

    private applyFilter(query: string): void {
        const f = query.toLowerCase().trim();
        this.filteredItems = f
            ? this.allItems.filter((item) => item.fullPath.toLowerCase().includes(f))
            : this.allItems;
    }
}
