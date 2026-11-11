import { CdkTrapFocus } from '@angular/cdk/a11y';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    Output,
    signal,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';
import { GraphSessionStatus } from '@shared/models';

interface StatusOption {
    value: string;
    label: string;
    color: string;
    icon: string;
}

@Component({
    selector: 'app-flow-session-status-filter-dropdown',
    imports: [CdkTrapFocus, ClickOutsideDirective, AppSvgIconComponent, MatTooltip],
    template: `
        <div
            class="status-filter-dropdown-custom"
            [class.open]="open"
            (appClickOutside)="closeDropdown()"
            (keydown.escape)="closeOnEscape($event)"
        >
            <button
                type="button"
                class="dropdown-toggle"
                aria-haspopup="menu"
                [attr.aria-expanded]="open"
                matTooltip="Filter by status"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-icons">
                    @if (selectedValues().length === 0) {
                        Status
                    } @else if (selectedValues().length === 1) {
                        {{ selectedOptions()[0].label }}
                    } @else {
                        Mixed ({{ selectedValues().length }})
                    }
                </span>
                <app-svg-icon
                    icon="menu"
                    size="16px"
                ></app-svg-icon>
            </button>

            @if (open) {
                <!-- Takes the focus when it opens and hands it back to the toggle when it closes. -->
                <ul
                    class="dropdown-menu"
                    role="menu"
                    cdkTrapFocus
                    [cdkTrapFocusAutoCapture]="true"
                >
                    @for (option of options; track option.value) {
                        <li role="none">
                            <button
                                type="button"
                                class="status-option"
                                role="menuitemcheckbox"
                                [class.selected]="selectedValues().includes(option.value)"
                                [attr.aria-checked]="selectedValues().includes(option.value)"
                                [matTooltip]="option.label"
                                (click)="toggleStatus(option.value, $event)"
                            >
                                <span [style.color]="option.color">
                                    <app-svg-icon
                                        class="status-icon"
                                        [icon]="option.icon"
                                        size="16px"
                                    ></app-svg-icon>
                                    {{ option.label }}
                                </span>
                                @if (selectedValues().includes(option.value)) {
                                    <span class="checkmark">&#10003;</span>
                                }
                            </button>
                        </li>
                    }
                </ul>
            }
        </div>
    `,
    styleUrls: ['./flow-session-status-filter-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowSessionStatusFilterDropdownComponent {
    @Input() value: string[] = [];
    @Output() valueChange = new EventEmitter<string[]>();
    public open = false;

    public options: StatusOption[] = [
        { value: 'all', label: 'All', color: '#b0b8c1', icon: 'menu' },
        {
            value: GraphSessionStatus.RUNNING,
            label: 'Running',
            color: '#5e9eff',
            icon: 'play',
        },
        {
            value: GraphSessionStatus.ERROR,
            label: 'Error',
            color: '#e0575b',
            icon: 'warning',
        },
        {
            value: GraphSessionStatus.ENDED,
            label: 'Completed',
            color: '#3bb77e',
            icon: 'check',
        },
        {
            value: GraphSessionStatus.WAITING_FOR_USER,
            label: 'Waiting',
            color: '#ffc14d',
            icon: 'clock',
        },
        {
            value: GraphSessionStatus.PENDING,
            label: 'Pending',
            color: '#b0b8c1',
            icon: 'clock',
        },
        {
            value: GraphSessionStatus.EXPIRED,
            label: 'Expired',
            color: '#888888',
            icon: 'clock',
        },
        {
            value: GraphSessionStatus.STOP,
            label: 'Stopped',
            color: '#5a5454ff',
            icon: 'x',
        },
    ];

    private _cdr: ChangeDetectorRef;
    public selectedValues = signal<string[]>([]);
    public selectedOptions = signal<StatusOption[]>([]);

    constructor(cdr: ChangeDetectorRef) {
        this._cdr = cdr;
    }

    ngOnChanges() {
        this.updateSelected();
    }

    updateSelected() {
        const vals = !this.value || this.value.length === 0 || this.value.includes('all') ? [] : this.value;
        this.selectedValues.set(vals);
        this.selectedOptions.set(this.options.filter((opt) => vals.includes(opt.value)));
        this._cdr.markForCheck();
    }

    public toggleDropdown(event: Event) {
        event.stopPropagation();
        this.open = !this.open;
        this._cdr.markForCheck();
    }

    /** Escape closes the open menu, and goes no further (it would close a dialog around it). */
    public closeOnEscape(event: Event): void {
        if (!this.open) return;
        event.stopPropagation();
        this.closeDropdown();
    }

    public closeDropdown() {
        this.open = false;
        this._cdr.markForCheck();
    }

    public toggleStatus(value: string, event: Event) {
        event.stopPropagation();
        let newValues = [...this.selectedValues()];
        if (value === 'all') {
            newValues = [];
            this.closeDropdown();
        } else {
            if (newValues.includes(value)) {
                newValues = newValues.filter((v) => v !== value);
            } else {
                newValues.push(value);
            }
        }
        this.valueChange.emit(newValues.length === 0 ? ['all'] : newValues);
    }
}
