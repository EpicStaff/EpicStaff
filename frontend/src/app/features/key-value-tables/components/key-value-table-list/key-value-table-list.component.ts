import { Component, computed, input, output, signal } from '@angular/core';
import { ButtonComponent, IconButtonComponent, SearchComponent } from '@shared/components';

import { KeyValueTable } from '../../models/key-value-table.model';

// Short lists are scanned by eye; the name filter appears only past this many tables.
const FILTER_THRESHOLD = 8;

@Component({
    selector: 'app-key-value-table-list',
    imports: [ButtonComponent, IconButtonComponent, SearchComponent],
    templateUrl: './key-value-table-list.component.html',
    styleUrls: ['./key-value-table-list.component.scss'],
})
export class KeyValueTableListComponent {
    readonly tables = input.required<KeyValueTable[]>();
    readonly selectedId = input<number | null>(null);
    readonly canCreate = input(false);
    readonly canRename = input(false);
    readonly canDelete = input(false);

    readonly createRequested = output<void>();
    readonly selected = output<KeyValueTable>();
    readonly renameRequested = output<KeyValueTable>();
    readonly deleteRequested = output<KeyValueTable>();

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
