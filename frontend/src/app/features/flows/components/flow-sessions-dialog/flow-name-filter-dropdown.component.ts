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
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';

import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';

interface FlowOption {
    id: number;
    name: string;
}

@Component({
    selector: 'app-flow-name-filter-dropdown',
    standalone: true,
    imports: [CommonModule, FormsModule, ClickOutsideDirective, CheckboxComponent, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    styles: [
        `
            :host .dropdown-toggle {
                border: none !important;
                background: transparent !important;
                min-width: unset !important;
                width: auto !important;
                justify-content: flex-start !important;
            }
            :host .dropdown-panel {
                z-index: 1100 !important;
                min-width: 350px !important;
            }
            :host .node-filter-dropdown {
                margin-left: 0;
            }
        `,
    ],
    template: `
        <div
            class="node-filter-dropdown"
            [class.open]="open"
            (appClickOutside)="onCancel()"
        >
            <button
                class="dropdown-toggle"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-label">
                    Flow Name
                    <app-svg-icon
                        icon="menu"
                        size="16px"
                    ></app-svg-icon>
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
                            <button
                                class="clear-search"
                                (click)="clearSearch($event)"
                            >
                                <i class="ti ti-x"></i>
                            </button>
                        }
                    </div>
                    <ul class="dropdown-menu">
                        @for (flow of filteredFlows; track flow.id) {
                            <li
                                class="group-item"
                                (click)="toggleFlow(flow.name)"
                            >
                                <app-checkbox [checked]="isChecked(flow.name)"></app-checkbox>
                                <span>{{ flow.name }}</span>
                            </li>
                        }
                        @if (filteredFlows.length === 0) {
                            <li class="no-results">
                                <i class="ti ti-search-off"></i>
                                No flows found
                            </li>
                        }
                    </ul>

                    <div class="trigger-dropdown-footer">
                        <button
                            class="clear-filter-btn"
                            (click)="onClear()"
                        >
                            Clear Filter
                        </button>
                        <button
                            class="cancel-btn"
                            (click)="onCancel()"
                        >
                            Cancel
                        </button>
                        <button
                            class="save-btn"
                            (click)="onSave()"
                        >
                            Save Changes
                        </button>
                    </div>
                </div>
            }
        </div>
    `,
    styleUrls: ['./flow-session-node-filter-dropdown.component.scss'],
})
export class FlowNameFilterDropdownComponent implements OnChanges {
    @Input() flows: FlowOption[] = [];
    @Input() value: string[] = [];
    @Output() valueChange = new EventEmitter<string[]>();

    public open = false;
    public searchQuery = '';
    public draftValue: string[] = [];
    public filteredFlows: FlowOption[] = [];

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['flows'] || changes['value']) {
            this.draftValue = [...this.value];
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

    public isChecked(name: string): boolean {
        return this.draftValue.includes(name);
    }

    public toggleFlow(name: string): void {
        if (this.isChecked(name)) {
            this.draftValue = this.draftValue.filter((n) => n !== name);
        } else {
            this.draftValue = [...this.draftValue, name];
        }
        this.cdr.markForCheck();
    }

    public toggleDropdown(event: Event): void {
        event.stopPropagation();
        this.open = !this.open;
        if (this.open) {
            this.draftValue = [...this.value];
            this.applySearch(this.searchQuery);
        }
        this.cdr.markForCheck();
    }

    public onClear(): void {
        this.draftValue = [];
        this.valueChange.emit([]);
        this.closeDropdown();
    }

    public onCancel(): void {
        this.closeDropdown();
    }

    public onSave(): void {
        this.valueChange.emit([...this.draftValue]);
        this.closeDropdown();
    }

    private closeDropdown(): void {
        this.open = false;
        this.cdr.markForCheck();
    }
}
