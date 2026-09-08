import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { ToolSortOrder } from '../../../../models/tool-filter.model';

export interface ToolsSortMenuItem {
    readonly value: ToolSortOrder;
    readonly label: string;
}

export const TOOLS_SORT_MENU_ITEMS: readonly ToolsSortMenuItem[] = [
    { value: 'last_modified', label: 'Last modified' },
    { value: 'name_asc', label: 'Name A to Z' },
    { value: 'name_desc', label: 'Name Z to A' },
    { value: 'most_used', label: 'Most Used' },
    { value: 'unused_first', label: 'Unused First' },
];

@Component({
    selector: 'app-tools-sort-menu',
    imports: [],
    templateUrl: './tools-sort-menu.component.html',
    styleUrls: ['./tools-sort-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsSortMenuComponent {
    public readonly activeSort = input<ToolSortOrder>('default');
    public readonly sortSelected = output<ToolSortOrder>();

    public readonly items = TOOLS_SORT_MENU_ITEMS;

    public onSelect(value: ToolSortOrder): void {
        this.sortSelected.emit(value);
    }
}
