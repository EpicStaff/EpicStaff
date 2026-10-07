import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { Component, computed, inject, input, output, signal } from '@angular/core';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    ButtonComponent,
    SearchComponent,
} from '@shared/components';

import { KeyValueTable } from '../../models/key-value-table.model';

// Short lists are scanned by eye; the name filter appears only past this many tables.
const FILTER_THRESHOLD = 8;

@Component({
    selector: 'app-key-value-table-list',
    imports: [AppSvgIconComponent, ButtonComponent, CdkMenu, CdkMenuItem, CdkMenuTrigger, SearchComponent],
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
    // Keeps the row's ⋮ shown while its menu is open, when neither hover nor focus is on the row any more.
    protected readonly menuOpenTableId = signal<number | null>(null);

    // Opens below the ⋮ from its left edge, as the Agents page row menu does; shifts or flips where there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);

    protected onRename(table: KeyValueTable, menuTrigger: CdkMenuTrigger, triggerButton: HTMLElement): void {
        this.closeMenuToTrigger(menuTrigger, triggerButton);
        this.renameRequested.emit(table);
    }

    protected onViewDetails(table: KeyValueTable, menuTrigger: CdkMenuTrigger, triggerButton: HTMLElement): void {
        this.closeMenuToTrigger(menuTrigger, triggerButton);
        this.authorshipDetailsDialog.open('Table Details', table, triggerButton);
    }

    protected onDelete(table: KeyValueTable, menuTrigger: CdkMenuTrigger, triggerButton: HTMLElement): void {
        this.closeMenuToTrigger(menuTrigger, triggerButton);
        this.deleteRequested.emit(table);
    }

    /**
     * A menu item fires before CdkMenu closes the menu and focuses the ⋮. Closing it first means the
     * dialog an item opens records the ⋮, not the menu item about to be destroyed, as where focus
     * returns on close — so focus comes back to the row, as it did with the old inline buttons.
     */
    private closeMenuToTrigger(menuTrigger: CdkMenuTrigger, triggerButton: HTMLElement): void {
        menuTrigger.close();
        triggerButton.focus();
    }
}
