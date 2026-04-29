import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    Output,
    signal,
} from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';
import { GraphSessionStatus } from '../../services/flows-sessions.service';

interface StatusOption {
    value: string;
    label: string;
    color: string;
    icon: string;
}

@Component({
    selector: 'app-flow-session-status-filter-dropdown',
    standalone: true,
    imports: [CommonModule, ClickOutsideDirective, AppSvgIconComponent],
    template: `
        <div
            class="status-filter-dropdown-custom"
            [class.open]="open"
            (appClickOutside)="closeDropdown()"
        >
            <button
                class="dropdown-toggle"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-icons">
                    @if (selectedValues().length === 0) {
                        <app-svg-icon
                            class="status-icon"
                            [icon]="options[0].icon"
                            size="16px"
                        ></app-svg-icon>
                        {{ options[0].label }}
                    } @else if (selectedValues().length === 1) {
                        <app-svg-icon
                            class="status-icon"
                            [icon]="selectedOptions()[0].icon"
                            size="16px"
                            [style.color]="selectedOptions()[0].color"
                        ></app-svg-icon>
                        {{ selectedOptions()[0].label }}
                    } @else {
                        <span class="icon-multi">
                            @for (opt of selectedOptions(); track opt.value) {
                                <app-svg-icon
                                    class="status-icon"
                                    [icon]="opt.icon"
                                    size="16px"
                                    [style.color]="opt.color"
                                ></app-svg-icon>
                            }
                        </span>
                        Mixed ({{ selectedValues().length }})
                    }
                </span>
                <span class="dropdown-arrow-wrapper">
                    <app-svg-icon
                        icon="chevron-down"
                        size="16px"
                        class="dropdown-arrow"
                    ></app-svg-icon>
                </span>
            </button>

            @if (open) {
                <ul class="dropdown-menu">
                    @for (option of options; track option.value) {
                        <li
                            (click)="toggleStatus(option.value, $event)"
                            [class.selected]="selectedValues().includes(option.value)"
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
        { value: 'all', label: 'All', color: '#b0b8c1', icon: 'list-numbers' },
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
