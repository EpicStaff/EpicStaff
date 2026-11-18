import { Component, computed, input } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { MultiSelectComponent } from '../multi-select/multi-select.component';
import { MultiSelectTriggerDirective } from '../multi-select/multi-select-trigger.directive';
import { SelectItem } from '../select/select.component';
import { AppTableComponent } from './table.component';

const DEFAULT_SECTION = 'General';
const TITLE = 'Table columns view';

/**
 * Toolbar button opening the "Table columns view" popover of an `<app-table>` with a `layoutKey`: one checkbox per
 * hideable column, sectioned by `headerGroup` (others under "General"). Changes apply on Save only.
 *
 * ```html
 * <app-table-column-picker [table]="table" />
 * <app-table #table layoutKey="my-table" ... />
 * ```
 */
@Component({
    selector: 'app-table-column-picker',
    imports: [AppSvgIconComponent, MatTooltip, MultiSelectComponent, MultiSelectTriggerDirective],
    template: `
        <app-multi-select
            #picker
            checkboxPosition="left"
            saveLabel="Save Changes"
            selectAllLabel="Show All"
            panelWidth="400px"
            panelHeight="450px"
            [headerTitle]="title"
            [hideTrigger]="true"
            [grouped]="true"
            [showSearch]="false"
            [uppercaseGroupLabels]="false"
            [sortSelectedToTop]="false"
            variant="outlined"
            [items]="items()"
            [selectedValues]="table().visibleHideableKeys()"
            (selectionChange)="onSave($event)"
        >
            <button
                type="button"
                class="column-picker-trigger"
                [class.open]="picker.isOpen()"
                [attr.aria-label]="title"
                [attr.aria-expanded]="picker.isOpen()"
                [matTooltip]="title"
                [appMultiSelectTrigger]="picker"
            >
                <app-svg-icon
                    icon="columns"
                    size="16px"
                />
            </button>
        </app-multi-select>
    `,
    styles: `
        .column-picker-trigger {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 40px;
            height: 40px;
            padding: 0;
            border: 1px solid var(--color-table-border);
            border-radius: 8px;
            background: transparent;
            color: var(--color-text-secondary);
            cursor: pointer;
            transition:
                color 0.15s ease,
                border-color 0.15s ease,
                background-color 0.15s ease;

            &:is(:hover, :focus-visible):not(.open) {
                color: var(--accent-color);
                border-color: var(--accent-color);
            }

            &.open {
                background: var(--accent-color);
                border-color: var(--accent-color);
                color: var(--color-text-primary);
            }
        }
    `,
})
export class TableColumnPickerComponent {
    readonly table = input.required<AppTableComponent>();

    protected readonly items = computed<SelectItem<string>[]>(() =>
        this.table()
            .hideableColumns()
            .map((col) => ({ name: col.label ?? col.key, value: col.key, group: col.headerGroup ?? DEFAULT_SECTION }))
    );

    protected readonly title = TITLE;

    protected onSave(values: unknown[]): void {
        this.table().setVisibleColumns(values.filter((value): value is string => typeof value === 'string'));
    }
}
