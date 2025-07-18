import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { GraphSessionStatus } from '../../services/flows-sessions.service';
import { ClickOutsideDirective } from '../../../../shared/directives/click-outside.directive';

interface StatusOption {
  value: string;
  label: string;
  color: string;
  icon: string;
}

@Component({
  selector: 'app-flow-session-status-filter-dropdown',
  standalone: true,
  imports: [CommonModule, ClickOutsideDirective],
  template: `
    <div
      class="status-filter-dropdown-custom"
      [class.open]="open"
      (clickOutside)="closeDropdown()"
    >
      <button class="dropdown-toggle" (click)="toggleDropdown($event)">
        <span class="selected-icons">
          @if (selectedValues().length === 0) {
          <i [class]="options[0].icon"></i> {{ options[0].label }}
          } @else if (selectedValues().length === 1) {
          <i
            [class]="selectedOptions()[0].icon"
            [style.color]="selectedOptions()[0].color"
          ></i>
          {{ selectedOptions()[0].label }}
          } @else {
          <span class="icon-multi">
            @for (opt of selectedOptions(); track opt.value) {
            <i [class]="opt.icon" [style.color]="opt.color"></i>
            }
          </span>
          Mixed ({{ selectedValues().length }}) }
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
      <ul class="dropdown-menu">
        @for (option of options; track option.value) {
        <li
          (click)="toggleStatus(option.value, $event)"
          [class.selected]="selectedValues().includes(option.value)"
        >
          <span [style.color]="option.color">
            <i [class]="option.icon"></i>
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
    { value: 'all', label: 'All', color: '#b0b8c1', icon: 'ti ti-list' },
    {
      value: GraphSessionStatus.RUNNING,
      label: 'Running',
      color: '#5e9eff',
      icon: 'ti ti-player-play',
    },
    {
      value: GraphSessionStatus.ERROR,
      label: 'Error',
      color: '#e0575b',
      icon: 'ti ti-alert-triangle',
    },
    {
      value: GraphSessionStatus.ENDED,
      label: 'Completed',
      color: '#3bb77e',
      icon: 'ti ti-check',
    },
    {
      value: GraphSessionStatus.WAITING_FOR_USER,
      label: 'Waiting',
      color: '#ffc14d',
      icon: 'ti ti-hourglass',
    },
    {
      value: GraphSessionStatus.PENDING,
      label: 'Pending',
      color: '#b0b8c1',
      icon: 'ti ti-clock',
    },
    {
      value: GraphSessionStatus.EXPIRED,
      label: 'Expired',
      color: '#888888',
      icon: 'ti ti-clock-pause',
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
    // If 'all' is selected or nothing, treat as no filter
    const vals =
      !this.value || this.value.length === 0 || this.value.includes('all')
        ? []
        : this.value;
    this.selectedValues.set(vals);
    this.selectedOptions.set(
      this.options.filter((opt) => vals.includes(opt.value))
    );
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
      // Close dropdown when selecting "All"
      this.closeDropdown();
    } else {
      if (newValues.includes(value)) {
        newValues = newValues.filter((v) => v !== value);
      } else {
        newValues.push(value);
      }
      // Don't close dropdown when selecting individual options
    }
    this.valueChange.emit(newValues.length === 0 ? ['all'] : newValues);
  }
}
