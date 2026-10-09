import { Component, computed, input, linkedSignal, output, signal } from '@angular/core';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { ClickOutsideDirective } from '@shared/directives';

import { SessionRunType } from '../../services/flows-sessions.service';
import { SESSION_RUN_TYPE_LABELS } from './trigger-display.constants';

const ALL_RUN_TYPES: SessionRunType[] = ['test', 'live'];

@Component({
    selector: 'app-flow-session-type-filter-dropdown',
    imports: [ClickOutsideDirective, CheckboxComponent, AppSvgIconComponent],
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
            [class.open]="isOpen()"
            [class.has-value]="hasValue()"
            (appClickOutside)="onCancel()"
        >
            <button
                class="dropdown-toggle"
                (click)="toggleDropdown($event)"
            >
                <span class="selected-label">
                    Type
                    <app-svg-icon
                        icon="menu"
                        size="16px"
                    ></app-svg-icon>
                </span>
            </button>

            @if (isOpen()) {
                <div class="dropdown-panel">
                    <ul class="dropdown-menu">
                        @for (runType of runTypes; track runType) {
                            <li
                                class="group-item"
                                (click)="toggleRunType(runType)"
                            >
                                <app-checkbox [checked]="draftValue().includes(runType)"></app-checkbox>
                                <span>{{ labels[runType] }}</span>
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
export class FlowSessionTypeFilterDropdownComponent {
    readonly value = input<SessionRunType[]>([]);
    readonly valueChange = output<SessionRunType[]>();

    protected readonly isOpen = signal(false);
    protected readonly draftValue = linkedSignal(() => [...this.value()]);
    protected readonly hasValue = computed(() => this.value().length > 0);

    protected readonly runTypes = ALL_RUN_TYPES;
    protected readonly labels = SESSION_RUN_TYPE_LABELS;

    protected toggleRunType(runType: SessionRunType): void {
        this.draftValue.update((draft) =>
            draft.includes(runType) ? draft.filter((selected) => selected !== runType) : [...draft, runType]
        );
    }

    protected toggleDropdown(event: Event): void {
        event.stopPropagation();
        if (!this.isOpen()) {
            this.draftValue.set([...this.value()]);
        }
        this.isOpen.update((open) => !open);
    }

    protected onClear(): void {
        this.draftValue.set([]);
        this.valueChange.emit([]);
        this.isOpen.set(false);
    }

    protected onCancel(): void {
        this.isOpen.set(false);
    }

    protected onSave(): void {
        this.valueChange.emit([...this.draftValue()]);
        this.isOpen.set(false);
    }
}
