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

import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';

interface FlowOption {
    id: number;
    name: string;
}

@Component({
    selector: 'app-flow-name-filter-dropdown',
    standalone: true,
    imports: [CommonModule, FormsModule, ClickOutsideDirective],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="node-filter-dropdown" [class.open]="open" (appClickOutside)="closeDropdown()">
            <button class="dropdown-toggle" (click)="toggleDropdown($event)">
                <span class="selected-label">
                    <i class="ti ti-filter"></i>
                    {{ value ?? 'Filter by Flow' }}
                </span>
                <span class="dropdown-arrow-wrapper">
                    <svg class="dropdown-arrow" width="16" height="16" viewBox="0 0 24 24">
                        <path d="M7 10l5 5 5-5" stroke="currentColor" stroke-width="2" fill="none" />
                    </svg>
                </span>
            </button>
            @if (open) {
                <div class="dropdown-panel">
                    <div class="search-box">
                        <i class="ti ti-search search-icon"></i>
                        <input
                            type="text"
                            class="search-input"
                            placeholder="Search flows..."
                            [ngModel]="searchQuery"
                            (ngModelChange)="onSearchChange($event)"
                            (click)="$event.stopPropagation()"
                        />
                        @if (searchQuery) {
                            <button class="clear-search" (click)="clearSearch($event)">
                                <i class="ti ti-x"></i>
                            </button>
                        }
                    </div>
                    <ul class="dropdown-menu">
                        <li (click)="select(null, $event)" [class.selected]="value === null">
                            <i class="ti ti-list"></i>
                            <span>All Flows</span>
                            @if (value === null) {
                                <span class="checkmark">&#10003;</span>
                            }
                        </li>
                        @for (flow of filteredFlows; track flow.id) {
                            <li (click)="select(flow.name, $event)" [class.selected]="value === flow.name">
                                <span>{{ flow.name }}</span>
                                @if (value === flow.name) {
                                    <span class="checkmark">&#10003;</span>
                                }
                            </li>
                        }
                        @if (filteredFlows.length === 0) {
                            <li class="no-results">
                                <i class="ti ti-search-off"></i>
                                No flows found
                            </li>
                        }
                    </ul>
                    @if (value !== null) {
                        <div class="clear-filter-footer">
                            <button class="clear-filter-btn" (click)="select(null, $event)">Clear Filter</button>
                        </div>
                    }
                </div>
            }
        </div>
    `,
    styleUrls: ['./flow-session-node-filter-dropdown.component.scss'],
})
export class FlowNameFilterDropdownComponent implements OnChanges {
    @Input() flows: FlowOption[] = [];
    @Input() value: string | null = null;
    @Output() valueChange = new EventEmitter<string | null>();

    public open = false;
    public searchQuery = '';
    public filteredFlows: FlowOption[] = [];

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['flows'] || changes['value']) {
            this.applySearch(this.searchQuery);
        }
    }

    private applySearch(query: string): void {
        const q = query.trim().toLowerCase();
        this.filteredFlows = q ? this.flows.filter((f) => f.name.toLowerCase().includes(q)) : [...this.flows];
    }

    public onSearchChange(query: string): void {
        this.searchQuery = query;
        this.applySearch(query);
        this.cdr.markForCheck();
    }

    public clearSearch(event: Event): void {
        event.stopPropagation();
        this.searchQuery = '';
        this.applySearch('');
        this.cdr.markForCheck();
    }

    public toggleDropdown(event: Event): void {
        event.stopPropagation();
        this.open = !this.open;
        if (this.open) this.applySearch(this.searchQuery);
        this.cdr.markForCheck();
    }

    public closeDropdown(): void {
        this.open = false;
        this.cdr.markForCheck();
    }

    public select(name: string | null, event: Event): void {
        event.stopPropagation();
        this.valueChange.emit(name);
        this.closeDropdown();
    }
}
