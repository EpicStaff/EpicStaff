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
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';

import { TriggerType } from '../../services/flows-sessions.service';
import { getTriggerDisplay } from './trigger-display.constants';

const ALL_TRIGGER_TYPES: TriggerType[] = ['manual', 'schedule', 'webhook', 'telegram', 'parent_flow'];

@Component({
    selector: 'app-trigger-filter-dropdown',
    imports: [CdkTrapFocus, ClickOutsideDirective, CheckboxComponent, AppSvgIconComponent, MatTooltip],
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
                z-index: 9999 !important;
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
                matTooltip="Filter by trigger"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-label">
                    Trigger
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
                    <ul class="dropdown-menu">
                        @for (type of ALL_TRIGGER_TYPES; track type) {
                            <li
                                class="group-item"
                                (click)="toggleType(type)"
                            >
                                <app-checkbox
                                    [checked]="isChecked(type)"
                                    [ariaLabel]="getLabel(type)"
                                ></app-checkbox>
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
export class TriggerFilterDropdownComponent implements OnChanges {
    @Input() value: TriggerType[] = [];
    @Output() valueChange = new EventEmitter<TriggerType[]>();

    public get hasValue(): boolean {
        return this.value.length > 0;
    }

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
