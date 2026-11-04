import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    EventEmitter,
    inject,
    Injector,
    Input,
    OnChanges,
    Output,
    signal,
    SimpleChanges,
    ViewChild,
    viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { formatNodeLabel, nextListIndex } from '@shared/utils';

import { NodeModel } from '../../core/models/node.model';
import { KeymapService } from '../../services/keymap.service';
import { SearchNodeItemComponent } from './search-node-item/search-node-item.component';

let nextSearchId = 0;

@Component({
    selector: 'app-nodes-search',
    imports: [FormsModule, SearchNodeItemComponent, AppSvgIconComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    // Host listener instead of document.addEventListener so it is removed with the component
    // (the flow canvas is destroyed and re-created around version preview).
    host: {
        '(document:mousedown)': 'onDocumentMousedown($event)',
    },
    template: `
        <!-- Escape in the search closes only the search: handled here, ahead of the tooltip of the focused
             control, which would take the first one, and of the canvas and the node panel. -->
        <div
            class="nodes-search-container"
            [class.nodes-search-container--expanded]="isSearchVisible()"
            (keydown.escape)="onEscape($event)"
        >
            <div class="search-header">
                <!-- Search button with icon -->
                <button
                    #searchButton
                    type="button"
                    class="search-button"
                    [attr.aria-label]="isSearchVisible() ? 'Close search' : 'Search nodes'"
                    [attr.aria-expanded]="isSearchVisible()"
                    (click)="toggleSearchInput()"
                    [matTooltip]="
                        keymap.withShortcut(
                            isSearchVisible() ? 'Close search' : 'Search nodes',
                            'navigating.node-search'
                        )
                    "
                    matTooltipPosition="right"
                    [class.active]="isSearchVisible()"
                >
                    <app-svg-icon
                        icon="search"
                        size="1.1rem"
                    ></app-svg-icon>
                </button>

                <!-- Search input field (appears to the right of the icon) -->
                @if (isSearchVisible()) {
                    <div class="search-input-container">
                        <input
                            type="text"
                            class="search-input"
                            placeholder="Search nodes..."
                            aria-label="Search nodes"
                            role="combobox"
                            aria-autocomplete="list"
                            [attr.aria-expanded]="filteredNodes.length > 0"
                            [attr.aria-controls]="resultsId"
                            [attr.aria-activedescendant]="activeIndex() < 0 ? null : resultId(activeIndex())"
                            [(ngModel)]="searchQuery"
                            (ngModelChange)="updateSearch($event)"
                            (keydown)="onSearchKeydown($event)"
                            #searchInputRef
                        />
                        @if (searchQuery) {
                            <button
                                type="button"
                                class="clear-button"
                                aria-label="Clear search"
                                (click)="onClearClick()"
                                matTooltip="Clear search"
                                matTooltipPosition="right"
                            >
                                <app-svg-icon icon="x"></app-svg-icon>
                            </button>
                        }
                    </div>
                }
            </div>

            <!-- Search results (visible when expanded) -->
            @if (isSearchVisible() && (filteredNodes.length > 0 || searchQuery)) {
                <div class="search-results">
                    <!-- Add panel title -->
                    <div class="panel-title">
                        <h3>Search nodes ({{ filteredNodes.length }} found)</h3>
                    </div>
                    <ul
                        class="node-list"
                        role="listbox"
                        aria-label="Nodes"
                        [id]="resultsId"
                    >
                        @if (filteredNodes.length === 0 && searchQuery) {
                            <li class="no-results">No nodes match your search</li>
                        }
                        @for (node of filteredNodes; track node; let last = $last; let index = $index) {
                            <li
                                role="option"
                                [id]="resultId(index)"
                                [attr.aria-selected]="index === activeIndex()"
                                [class.last-node]="last"
                            >
                                <app-search-node-item
                                    [node]="node"
                                    [active]="index === activeIndex()"
                                    (nodeSelected)="onNodeSelected($event)"
                                    (nodeDoubleClicked)="onNodeDoubleClicked($event)"
                                ></app-search-node-item>
                            </li>
                        }
                    </ul>
                </div>
            }
        </div>
    `,
    styles: [
        `
            .nodes-search-container {
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                width: fit-content;
                min-width: 0;

                &--expanded {
                    width: min(350px, 100%);
                }
            }

            .search-header {
                display: flex;
                flex-direction: row;
                align-items: center;
                gap: 0.5rem;
                width: 100%;
            }

            .search-button {
                width: 36px;
                height: 36px;
                min-width: 36px;
                padding: 8px;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                transition: all 0.2s ease;
                position: relative;
                color: var(--gray-300);

                &:is(:hover, :focus-visible) {
                    background-color: var(--gray-750);
                }

                &:active {
                    transform: scale(0.95);
                }

                i {
                    font-size: 1.125rem;
                    color: var(--gray-300);
                }

                &.active {
                    background-color: var(--accent-color);
                    color: var(--white);

                    i {
                        color: var(--white);
                    }
                }
            }

            .search-input-container {
                position: relative;
                flex-grow: 1;
                width: 100%;
                min-width: 0;
            }

            .search-input {
                width: 100%;
                height: 38px;
                background-color: var(--gray-850, #1a1a1a);
                border: 1px solid var(--gray-750, #2f2f2f);
                border-radius: 4px;
                padding: 0 32px 0 12px;
                color: var(--gray-200, #e3e3e3);
                font-size: 0.8125rem;
                outline: none;

                &:focus {
                    border-color: var(--accent-color, #685fff);
                }

                &::placeholder {
                    color: var(--gray-500, #9b9b9b);
                }
            }

            .clear-button {
                position: absolute;
                right: 8px;
                top: 50%;
                transform: translateY(-50%);
                width: 18px;
                height: 18px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: transparent;
                border: none;
                padding: 0;
                cursor: pointer;
                color: var(--gray-400, #b4b4b4);
                transition: color 0.15s ease;

                &:hover {
                    color: var(--white, #fff);
                }

                i {
                    font-size: 0.625rem;
                }
            }

            .search-results {
                margin-top: 0.5rem;
                width: 100%;
                background-color: var(--vscode-panel-background, #151515);
                border: 1px solid var(--vscode-panel-border, #3e3e3eff);
                border-radius: 6px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                overflow: hidden;
                max-height: calc(100vh - 16.3rem);
                display: flex;
                flex-direction: column;
            }

            .panel-title {
                padding: 0.75rem 1rem;
                border-bottom: 1px solid var(--gray-750, #2f2f2f);

                h3 {
                    margin: 0;
                    color: var(--gray-200, #e3e3e3);
                    font-size: var(--text-body-medium-size);
                    font-weight: var(--text-body-medium-weight);
                }
            }

            .node-list {
                max-height: calc(100vh - 16.5rem);
                overflow-y: auto;
                padding: 0.75rem;
                list-style: none;
                margin: 0;

                .no-results {
                    color: var(--gray-500, #9b9b9b);
                    text-align: center;
                    padding: 0;
                    margin: 0;
                    font-size: 0.8125rem;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 32px;
                    background-color: var(--gray-850, #1a1a1a);
                    border-radius: 4px;
                }

                li {
                    padding: 0;
                    margin: 0;
                    margin-bottom: 10px;

                    &.last-node {
                        margin-bottom: 0;
                    }

                    &:only-child {
                        margin-bottom: 0;
                    }
                }
            }
        `,
    ],
})
export class NodesSearchComponent implements OnChanges {
    @Input() nodes: NodeModel[] = [];
    @ViewChild('searchInputRef') searchInputRef!: ElementRef<HTMLInputElement>;

    @Output() nodeSelected = new EventEmitter<NodeModel>();
    @Output() nodeDoubleClicked = new EventEmitter<{
        node: NodeModel;
        event: MouseEvent;
    }>();

    public searchQuery = '';
    public filteredNodes: NodeModel[] = [];
    public isSearchVisible = signal<boolean>(false);
    /** The result the arrow keys point at, or -1; Enter opens it. */
    protected readonly activeIndex = signal(-1);
    protected readonly resultsId = `nodes-search-results-${nextSearchId++}`;

    private readonly searchButton = viewChild<ElementRef<HTMLButtonElement>>('searchButton');
    private readonly hostElement = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly injector = inject(Injector);
    protected readonly keymap = inject(KeymapService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        const options = { allowInEditable: true, destroyRef: this.destroyRef };
        this.keymap.register('navigating.node-search', () => this.toggleSearchInput(), options);
        this.keymap.register('editing.escape', () => this.closeSearch(), options);
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['nodes']) {
            this.updateSearch(this.searchQuery);
        }
    }

    protected onDocumentMousedown(event: MouseEvent): void {
        if (this.isSearchVisible() && !this.hostElement.nativeElement.contains(event.target as Node)) {
            this.closeSearch();
        }
    }

    public toggleSearchInput(): void {
        this.isSearchVisible.update((value) => !value);

        if (this.isSearchVisible()) {
            // Show all nodes when opening
            this.searchQuery = '';
            this.filteredNodes = [...this.nodes];

            setTimeout(() => {
                if (this.searchInputRef) {
                    this.searchInputRef.nativeElement.focus();
                }
            }, 100);
        } else {
            // Clear search when closing
            this.clearSearch();
        }
    }

    private nodeMatchesSearch(node: NodeModel, query: string): boolean {
        // Empty query should show all nodes
        if (!query.trim()) {
            return true;
        }

        // Search by node name and number, as the result list labels it
        if (node.node_name && formatNodeLabel(node).toLowerCase().includes(query)) {
            return true;
        }

        // Search by node type
        if (node.type && node.type.toLowerCase().includes(query)) {
            return true;
        }

        // Search in node data if available
        if (node.data) {
            // Check for common data properties
            if (typeof node.data === 'object') {
                const dataValues = Object.values(node.data);
                for (const value of dataValues) {
                    if (typeof value === 'string' && value.toLowerCase().includes(query)) {
                        return true;
                    }
                }
            }
        }

        return false;
    }

    public updateSearch(query: string): void {
        this.searchQuery = query;
        this.activeIndex.set(-1);

        // Filter nodes based on search query
        if (!query.trim()) {
            this.filteredNodes = [...this.nodes];
        } else {
            const queryLower = query.toLowerCase().trim();
            this.filteredNodes = this.nodes.filter((node) => this.nodeMatchesSearch(node, queryLower));
        }
    }

    /** The Clear button goes away with the text: the focus goes back to the search box. */
    protected onClearClick(): void {
        this.clearSearch();
        this.searchInputRef?.nativeElement.focus();
    }

    public clearSearch(): void {
        this.searchQuery = '';
        this.activeIndex.set(-1);
        this.filteredNodes = [];
    }

    protected onEscape(event: Event): void {
        if (event.defaultPrevented || !this.isSearchVisible()) return;
        event.stopPropagation();
        this.closeSearch();
        // The search box is gone: the focus goes back to the button that opens it.
        afterNextRender(() => this.searchButton()?.nativeElement.focus(), { injector: this.injector });
    }

    public closeSearch(): void {
        if (this.isSearchVisible()) {
            this.toggleSearchInput();
        }
    }

    public onNodeSelected(node: NodeModel): void {
        // A clicked result becomes the highlighted one, so the arrows go on from there.
        this.activeIndex.set(this.filteredNodes.indexOf(node));
        this.nodeSelected.emit(node);
    }

    protected resultId(index: number): string {
        return `${this.resultsId}-${index}`;
    }

    // Focus stays in the field so typing goes on; the arrows move the highlight and Enter opens it.
    protected onSearchKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            const node = this.filteredNodes[this.activeIndex()];
            if (node) {
                event.preventDefault();
                this.onNodeSelected(node);
            }
            return;
        }
        // Home and End stay with the text field, for its caret.
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        const next = nextListIndex(event.key, this.activeIndex(), this.filteredNodes.length);
        if (next === null) return;
        event.preventDefault();
        this.activeIndex.set(next);
        this.hostElement.nativeElement
            .querySelector(`#${CSS.escape(this.resultId(next))}`)
            ?.scrollIntoView?.({ block: 'nearest' });
    }

    public onNodeDoubleClicked(data: { node: NodeModel; event: MouseEvent }): void {
        this.nodeDoubleClicked.emit(data);
    }
}
