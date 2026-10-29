import { CdkTrapFocus } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { FlowSortOrder } from '../../../../models/flow-filter.model';

export interface FlowsSortMenuItem {
    readonly value: FlowSortOrder;
    readonly label: string;
}

export const FLOWS_SORT_MENU_ITEMS: readonly FlowsSortMenuItem[] = [
    { value: 'last_modified', label: 'Last modified' },
    { value: 'name_asc', label: 'Name A to Z' },
    { value: 'name_desc', label: 'Name Z to A' },
];

@Component({
    selector: 'app-flows-sort-menu',
    imports: [CdkTrapFocus, MatTooltip],
    templateUrl: './flows-sort-menu.component.html',
    styleUrls: ['./flows-sort-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsSortMenuComponent {
    public readonly activeSort = input<FlowSortOrder>('default');
    public readonly sortSelected = output<FlowSortOrder>();

    public readonly items = FLOWS_SORT_MENU_ITEMS;

    public onSelect(value: FlowSortOrder): void {
        this.sortSelected.emit(value);
    }
}
