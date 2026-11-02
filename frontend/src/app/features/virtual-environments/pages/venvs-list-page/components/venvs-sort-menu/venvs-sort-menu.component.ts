import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { VenvSortOrder } from '../../../../models/venv.model';

export interface VenvsSortMenuItem {
    readonly value: VenvSortOrder;
    readonly label: string;
}

// `default` is the order the venvs were created in, which is what the backend sorts by when
// it is asked for nothing. "Last modified" is not among them: no endpoint offers that order.
export const VENVS_SORT_MENU_ITEMS: readonly VenvsSortMenuItem[] = [
    { value: 'default', label: 'Default' },
    { value: 'name_asc', label: 'Name A to Z' },
    { value: 'name_desc', label: 'Name Z to A' },
];

@Component({
    selector: 'app-venvs-sort-menu',
    imports: [],
    templateUrl: './venvs-sort-menu.component.html',
    styleUrls: ['./venvs-sort-menu.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VenvsSortMenuComponent {
    public readonly activeSort = input<VenvSortOrder>('default');
    public readonly sortSelected = output<VenvSortOrder>();

    public readonly items = VENVS_SORT_MENU_ITEMS;

    public onSelect(value: VenvSortOrder): void {
        this.sortSelected.emit(value);
    }
}
