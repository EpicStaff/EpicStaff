import { Component, input, output } from '@angular/core';
import { IconButtonComponent } from '@shared/components';

import { PersistenceTable } from '../../models/persistence-table.model';

@Component({
    selector: 'app-persistence-table-list',
    imports: [IconButtonComponent],
    templateUrl: './persistence-table-list.component.html',
    styleUrls: ['./persistence-table-list.component.scss'],
})
export class PersistenceTableListComponent {
    readonly tables = input.required<PersistenceTable[]>();
    readonly selectedId = input<number | null>(null);
    readonly canManage = input(false);

    readonly selected = output<PersistenceTable>();
    readonly renameRequested = output<PersistenceTable>();
    readonly deleteRequested = output<PersistenceTable>();
}
