import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, output, ViewChild } from '@angular/core';

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
                padding: var(--space-sm);
                border-bottom: 1px solid var(--color-divider-subtle);

                input {
                    width: 100%;
                    box-sizing: border-box;
                    padding: var(--space-xs) var(--space-md);
                    background: var(--color-input-background);
                    border: 1px solid var(--color-input-border);
                    border-radius: 4px;
                    color: var(--color-text-primary);
                    font-size: var(--font-size-sm);
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
                padding: var(--space-2xs);
            }

            .vpf-empty {
                padding: var(--space-md);
                text-align: center;
                color: var(--color-text-secondary);
                font-size: var(--font-size-sm);
            }

            .vpf-item {
                display: flex;
                align-items: center;
                gap: var(--space-xs);
                width: 100%;
                text-align: left;
                padding: var(--space-xs) var(--space-sm);
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
                font-size: var(--font-size-2xs);
                font-weight: var(--font-weight-semibold);
                padding: var(--space-3xs) var(--space-xs);
                border-radius: 3px;
                background: rgba(104, 95, 255, 0.25);
                color: rgba(170, 160, 255, 0.9);
                letter-spacing: 0.02em;
                text-transform: lowercase;
            }

            .vpf-label {
                flex: 1;
                min-width: 0;
                font-size: var(--font-size-sm);
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

    private allItems: PickerItem[] = [];
    filteredItems: PickerItem[] = [];

    pathSelected = output<string>();

    ngAfterViewInit(): void {
        this.searchInputRef.nativeElement.focus();
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
        const f = (event.target as HTMLInputElement).value.toLowerCase().trim();
        this.filteredItems = f
            ? this.allItems.filter((item) => item.fullPath.toLowerCase().includes(f))
            : this.allItems;
    }
}
