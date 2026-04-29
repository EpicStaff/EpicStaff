import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    Output,
    SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NodeGroup } from 'src/app/shared/models/node-group.model';

@Component({
    selector: 'app-flow-session-node-filter-dropdown',
    standalone: true,
    imports: [CommonModule, FormsModule],
    changeDetection: ChangeDetectionStrategy.Default,
    template: `
        <div
            class="node-filter-dropdown"
            [class.open]="open"
            (clickOutside)="closeDropdown()"
        >
            <button
                class="dropdown-toggle"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-label">
                    <i class="ti ti-filter"></i>
                    {{ selectedValue ?? 'Filter by Node name' }}
                </span>
                <span class="dropdown-arrow-wrapper">
                    <svg
                        class="dropdown-arrow"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                    >
                        <path
                            d="M7 10l5 5 5-5"
                            stroke="currentColor"
                            stroke-width="2"
                            fill="none"
                        />
                    </svg>
                </span>
            </button>

            @if (open) {
                <div class="dropdown-panel">
                    <div class="search-box">
                        <i class="ti ti-search search-icon"></i>
                        <input
                            #searchInput
                            type="text"
                            class="search-input"
                            placeholder="Search nodes..."
                            [ngModel]="searchQuery"
                            (ngModelChange)="onSearchChange($event)"
                            (click)="$event.stopPropagation()"
                        />
                        @if (searchQuery) {
                            <button
                                class="clear-search"
                                (click)="clearSearch($event)"
                            >
                                <i class="ti ti-x"></i>
                            </button>
                        }
                    </div>

                    <ul class="dropdown-menu">
                        <li
                            (click)="selectNode(null, $event)"
                            [class.selected]="selectedValue === null"
                        >
                            <i class="ti ti-list"></i>
                            <span>All Nodes</span>
                            @if (selectedValue === null) {
                                <span class="checkmark">&#10003;</span>
                            }
                        </li>

                        @for (group of filteredGroups; track group.label) {
                            @if (group.nodes.length > 0) {
                                <li class="group-header">
                                    <i
                                        [class]="group.icon"
                                        [style.color]="group.color"
                                    ></i>
                                    <span>{{ group.label }}</span>
                                </li>
                                @for (node of group.nodes; track node) {
                                    <li
                                        class="group-item"
                                        (click)="selectNode(node, $event)"
                                        [class.selected]="selectedValue === node"
                                    >
                                        <span>{{ node }}</span>
                                        @if (selectedValue === node) {
                                            <span class="checkmark">&#10003;</span>
                                        }
                                    </li>
                                }
                            }
                        }

                        @if (hasNoResults) {
                            <li class="no-results">
                                <i class="ti ti-search-off"></i>
                                No nodes found
                            </li>
                        }
                    </ul>

                    @if (selectedValue) {
                        <div class="clear-filter-footer">
                            <button
                                class="clear-filter-btn"
                                (click)="selectNode(null, $event)"
                            >
                                Clear Filter
                            </button>
                        </div>
                    }
                </div>
            }
        </div>
    `,
    styleUrls: ['./flow-session-node-filter-dropdown.component.scss'],
})
export class FlowSessionNodeFilterDropdownComponent implements OnChanges {
    @Input() nodeGroups: NodeGroup[] = [];
    @Input() value: string | null = null;
    @Output() valueChange = new EventEmitter<string | null>();

    public open = false;
    public selectedValue: string | null = null;
    public searchQuery = '';
    public filteredGroups: NodeGroup[] = [];

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['value']) {
            this.selectedValue = this.value;
        }
        if (changes['nodeGroups']) {
            this.applySearch(this.searchQuery);
        }
    }

    private applySearch(query: string): void {
        const search = query.trim().toLowerCase();
        if (!search) {
            this.filteredGroups = this.nodeGroups.map((g) => ({ ...g }));
            return;
        }
        this.filteredGroups = this.nodeGroups
            .map((g) => ({
                ...g,
                nodes: g.nodes.filter((n) => n.toLowerCase().includes(search)),
            }))
            .filter((g) => g.nodes.length > 0);
    }

    public get hasNoResults(): boolean {
        return this.filteredGroups.length === 0 || this.filteredGroups.every((g) => g.nodes.length === 0);
    }

    public onSearchChange(query: string): void {
        this.searchQuery = query;
        this.applySearch(query);
    }

    public clearSearch(event: Event): void {
        event.stopPropagation();
        this.searchQuery = '';
        this.applySearch('');
    }

    public toggleDropdown(event: Event): void {
        event.stopPropagation();
        this.open = !this.open;
        if (this.open) {
            this.applySearch(this.searchQuery);
        }
    }

    public closeDropdown(): void {
        this.open = false;
    }

    public selectNode(node: string | null, event: Event) {
        event.stopPropagation();
        this.selectedValue = node;
        this.valueChange.emit(node);
        this.closeDropdown();
    }
}
