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
import { CheckboxComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';

import { TriggerType } from '../../services/flows-sessions.service';
import { getTriggerDisplay } from './trigger-display.constants';

const ALL_TRIGGER_TYPES: TriggerType[] = ['manual', 'schedule', 'webhook', 'telegram', 'parent_flow'];

@Component({
    selector: 'app-trigger-filter-dropdown',
    standalone: true,
    imports: [CommonModule, ClickOutsideDirective, CheckboxComponent],
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
                    <i class="ti ti-filter"></i>
                    @if (value.length === 0) {
                        Trigger
                    } @else {
                        Trigger ({{ value.length }})
                    }
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
                    <ul class="dropdown-menu">
                        @for (type of ALL_TRIGGER_TYPES; track type) {
                            <li
                                class="group-item"
                                (click)="toggleType(type)"
                            >
                                <app-checkbox [checked]="isChecked(type)"></app-checkbox>
                                @if (getIcon(type)) {
                                    <i
                                        [class]="getIcon(type)"
                                        [style.color]="getColor(type)"
                                    ></i>
                                }
                                <span>{{ getLabel(type) }}</span>
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
export class TriggerFilterDropdownComponent implements OnChanges {
    @Input() value: TriggerType[] = [];
    @Output() valueChange = new EventEmitter<TriggerType[]>();

    public open = false;
    public draftValue: TriggerType[] = [];
    public readonly ALL_TRIGGER_TYPES = ALL_TRIGGER_TYPES;

    constructor(private cdr: ChangeDetectorRef) {}

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['value']) {
            this.draftValue = [...this.value];
        }
    }

    public getLabel(type: TriggerType): string {
        return getTriggerDisplay(type).label;
    }

    public getIcon(type: TriggerType): string | null {
        return getTriggerDisplay(type).icon;
    }

    public getColor(type: TriggerType): string | null {
        return getTriggerDisplay(type).color;
    }

    public isChecked(type: TriggerType): boolean {
        return this.draftValue.includes(type);
    }

    public toggleType(type: TriggerType): void {
        if (this.isChecked(type)) {
            this.draftValue = this.draftValue.filter((t) => t !== type);
        } else {
            this.draftValue = [...this.draftValue, type];
        }
        this.cdr.markForCheck();
    }

    public toggleDropdown(event: Event): void {
        event.stopPropagation();
        this.open = !this.open;
        if (this.open) {
            this.draftValue = [...this.value];
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
