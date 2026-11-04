import { CdkTrapFocus } from '@angular/cdk/a11y';
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
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';

interface FlowOption {
    id: number;
    name: string;
}

@Component({
    selector: 'app-flow-name-filter-dropdown',
    imports: [CdkTrapFocus, FormsModule, ClickOutsideDirective, CheckboxComponent, AppSvgIconComponent, MatTooltip],
    changeDetection: ChangeDetectionStrategy.OnPush,
    styles: [
        `
            :host .dropdown-toggle {
                border: none !important;
                background: transparent !important;
                min-width: unset !important;
                width: auto !important;
                justify-content: flex-start !important;
                font: inherit !important;
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
            [class.has-value]="hasValue"
            (appClickOutside)="onCancel()"
            (keydown.escape)="closeOnEscape($event)"
        >
            <button
                type="button"
                class="dropdown-toggle"
                aria-haspopup="dialog"
                [attr.aria-expanded]="open"
                matTooltip="Filter by flow name"
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
                <!-- Takes the focus when it opens and hands it back to the toggle when it closes. -->
                <div
                    class="dropdown-panel"
                    cdkTrapFocus
                    [cdkTrapFocusAutoCapture]="true"
                >
                    <div class="search-box">
                        <i class="ti ti-search search-icon"></i>
                        <input
                            type="text"
                            class="search-input"
                            placeholder="Search flows..."
                            aria-label="Search flows"
                            matTooltip="Search flows"
                            [ngModel]="searchQuery"
                            (ngModelChange)="onSearchChange($event)"
                            (click)="$event.stopPropagation()"
                        />
                        @if (searchQuery) {
                            <button
                                type="button"
                                class="clear-search"
                                aria-label="Clear search"
                                matTooltip="Clear search"
                                (click)="clearSearch($event)"
                            >
                                <i
                                    class="ti ti-x"
                                    aria-hidden="true"
                                ></i>
                            </button>
                        }
                    </div>
                    <ul class="dropdown-menu">
                        @for (flow of filteredFlows; track flow.id) {
                            <li
                                class="group-item"
                                (click)="toggleFlow(flow.name)"
                            >
                                <app-checkbox
                                    [checked]="isChecked(flow.name)"
                                    [ariaLabel]="flow.name"
                                ></app-checkbox>
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
                            type="button"
                            class="clear-filter-btn"
                            matTooltip="Clear Filter"
                            (click)="onClear()"
                        >
                            Clear Filter
                        </button>
                        <button
                            type="button"
                            class="cancel-btn"
                            matTooltip="Cancel"
                            (click)="onCancel()"
                        >
                            Cancel
                        </button>
                        <button
                            type="button"
                            class="save-btn"
                            matTooltip="Save Changes"
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

    public get hasValue(): boolean {
        return this.value.length > 0;
    }

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

    /** Escape closes the open panel without saving, and goes no further (it would close a dialog around it). */
    public closeOnEscape(event: Event): void {
        if (!this.open) return;
        event.stopPropagation();
        this.onCancel();
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
