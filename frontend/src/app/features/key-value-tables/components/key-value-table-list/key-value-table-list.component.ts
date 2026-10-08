import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { Component, computed, input, output, signal } from '@angular/core';
import { ButtonComponent, IconButtonComponent, SearchComponent } from '@shared/components';

import { KeyValueTable } from '../../models/key-value-table.model';

// Short lists are scanned by eye; the name filter appears only past this many tables.
const FILTER_THRESHOLD = 8;

interface TruncatedName {
    element: HTMLElement;
    name: string;
}

@Component({
    selector: 'app-key-value-table-list',
    imports: [ButtonComponent, IconButtonComponent, OverlayModule, SearchComponent],
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

    // The full name of a truncated row. Not matTooltip: that one is centered over the name and, being wider than it,
    // would cross the sidebar's left edge; this one starts at the name's left edge and grows to the right.
    protected readonly truncatedName = signal<TruncatedName | null>(null);
    protected readonly namePositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetX: -12, offsetY: -8 },
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetX: -12, offsetY: 8 },
    ];

    protected showFullName(element: HTMLElement, name: string): void {
        const truncated = element.scrollWidth > element.clientWidth + 1;
        this.truncatedName.set(truncated ? { element, name } : null);
    }

    protected hideFullName(): void {
        this.truncatedName.set(null);
    }
}
