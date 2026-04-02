import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    OnChanges,
    OnInit,
    Output,
    signal,
    SimpleChanges,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { NodeModel } from '../../core/models/node.model';
import { SearchNodeItemComponent } from './search-node-item/search-node-item.component';

@Component({
    selector: 'app-nodes-search',
    standalone: true,
    imports: [CommonModule, FormsModule, SearchNodeItemComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="nodes-search-container">
            <div class="search-header">
                <!-- Search button with icon -->
                <button
                    class="search-button"
                    (click)="toggleSearchInput()"
                    [attr.title]="isSearchVisible() ? 'Close search' : 'Search nodes'"
                    [class.active]="isSearchVisible()"
                >
                    <i class="ti ti-search"></i>
                </button>

                <!-- Search input field (appears to the right of the icon) -->
                <div class="search-input-container" *ngIf="isSearchVisible()">
                    <input
                        type="text"
                        class="search-input"
                        placeholder="Search nodes..."
                        [(ngModel)]="searchQuery"
                        (ngModelChange)="updateSearch($event)"
                        #searchInputRef
                    />
                    <button *ngIf="searchQuery" class="clear-button" (click)="clearSearch()" title="Clear search">
                        <i class="ti ti-x"></i>
                    </button>
                </div>
            </div>

            <!-- Search results (visible when expanded) -->
            <div class="search-results" *ngIf="isSearchVisible() && (filteredNodes.length > 0 || searchQuery)">
                <!-- Add panel title -->
                <div class="panel-title">
                    <h3>Search nodes ({{ filteredNodes.length }} found)</h3>
                </div>

                <ul class="node-list">
                    <li class="no-results" *ngIf="filteredNodes.length === 0 && searchQuery">
                        No nodes match your search
                    </li>

                    <li *ngFor="let node of filteredNodes; let last = last" [class.last-node]="last">
                        <app-search-node-item
                            [node]="node"
                            (nodeSelected)="onNodeSelected($event)"
                            (nodeDoubleClicked)="onNodeDoubleClicked($event)"
                        ></app-search-node-item>
                    </li>
                </ul>
            </div>
        </div>
    `,
    styles: [
        `
            .nodes-search-container {
                display: flex;
                flex-direction: column;
                align-items: flex-start;
                width: 100%;
            }

            .search-header {
                display: flex;
                flex-direction: row;
                align-items: center;
                gap: 0.5rem;
                width: 100%;
            }

            .search-button {
                width: 38px;
                height: 38px;
                min-width: 38px;
                padding: 8px;
                background-color: var(--gray-800);
                border: 1px solid var(--gray-750);
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                transition: all 0.2s ease;
                outline: none;
                position: relative;

                &:hover {
                    background-color: var(--gray-750);
                }

                &:active {
                    transform: scale(0.95);
                }

                i {
                    font-size: 18px;
                    color: var(--gray-300);
                }

                &.active {
                    background-color: var(--accent-color);

                    i {
                        color: var(--white);
                    }
                }
            }

            .search-input-container {
                position: relative;
                flex-grow: 1;
                width: 100%;
                width: 17rem;
            }

            .search-input {
                width: 100%;
                height: 38px;
                background-color: var(--gray-850, #1a1a1a);
                border: 1px solid var(--gray-750, #2f2f2f);
                border-radius: 6px;
                padding: 0 32px 0 12px;
                color: var(--gray-200, #e3e3e3);
                font-size: 13px;
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
                background: var(--gray-700, #424242);
                border: none;
                border-radius: 50%;
                cursor: pointer;
                color: var(--gray-300, #cdcdcd);

                &:hover {
                    background-color: var(--gray-600, #676767);
                    color: var(--white, #fff);
                }

                i {
                    font-size: 10px;
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
                    font-size: 14px;
                    font-weight: 500;
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
                    font-size: 13px;
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
export class NodesSearchComponent implements OnInit, OnChanges {
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

    public ngOnInit(): void {
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                this.toggleSearchInput();
            }

            if (e.key === 'Escape' && this.isSearchVisible()) {
                this.toggleSearchInput();
            }
        });
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['nodes']) {
            this.updateSearch(this.searchQuery);
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

        // Search by node name
        if (node.node_name && node.node_name.toLowerCase().includes(query)) {
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

        // Filter nodes based on search query
        if (!query.trim()) {
            this.filteredNodes = [...this.nodes];
        } else {
            const queryLower = query.toLowerCase().trim();
            this.filteredNodes = this.nodes.filter((node) => this.nodeMatchesSearch(node, queryLower));
        }
    }

    public clearSearch(): void {
        this.searchQuery = '';
        this.filteredNodes = [];
    }

    public onNodeSelected(node: NodeModel): void {
        this.nodeSelected.emit(node);
    }

    public onNodeDoubleClicked(data: { node: NodeModel; event: MouseEvent }): void {
        this.nodeDoubleClicked.emit(data);
    }
}
