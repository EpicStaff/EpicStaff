import { Component, computed, input, output, signal } from '@angular/core';
import { IconButtonComponent, SearchComponent } from '@shared/components';

import { PersistenceTable } from '../../models/persistence-table.model';

// Short lists are scanned by eye; the name filter appears only past this many tables.
const FILTER_THRESHOLD = 8;

@Component({
    selector: 'app-persistence-table-list',
    imports: [IconButtonComponent, SearchComponent],
    templateUrl: './persistence-table-list.component.html',
    styleUrls: ['./persistence-table-list.component.scss'],
})
export class PersistenceTableListComponent {
    readonly tables = input.required<PersistenceTable[]>();
    readonly selectedId = input<number | null>(null);
    readonly canRename = input(false);
    readonly canDelete = input(false);

    readonly selected = output<PersistenceTable>();
    readonly renameRequested = output<PersistenceTable>();
    readonly deleteRequested = output<PersistenceTable>();

    readonly filterText = signal('');
    readonly showFilter = computed(() => this.tables().length > FILTER_THRESHOLD);
    // Ignores a leftover filter once the list shrinks back under the threshold and the field is gone.
    readonly visibleTables = computed(() => {
        const term = this.filterText().trim().toLowerCase();
        if (!this.showFilter() || !term) return this.tables();
        return this.tables().filter((table) => table.name.toLowerCase().includes(term));
    });
    readonly emptyMessage = computed(() => (this.tables().length ? 'No tables match your filter' : 'No tables yet'));
}
