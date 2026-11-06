import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    inject,
    Injector,
    input,
    output,
    signal,
    untracked,
    viewChildren,
} from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { BulkSelectDropdownComponent, ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';

import { TransferExportService } from '../../../../../../core/services/transfer-export.service';
import { FilesSearchService } from '../../../../../files/services/files-search.service';
import { RagType } from '../../../../models/base-rag.model';
import { GetCollectionRequest } from '../../../../models/collection.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { CollectionComponent } from './collection/collection.component';

@Component({
    selector: 'app-collections-list-sidebar',
    templateUrl: './collections-list-sidebar.component.html',
    styleUrls: ['./collections-list-sidebar.component.scss'],
    imports: [
        ButtonComponent,
        ReactiveFormsModule,
        FormsModule,
        CollectionComponent,
        SelectComponent,
        HasPermissionDirective,
        BulkSelectDropdownComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionsListItemSidebarComponent {
    collections = input<GetCollectionRequest[]>([]);

    onCreateCollection = output();
    readonly importRequested = output<void>();

    private readonly collectionCards = viewChildren(CollectionComponent);

    readonly selectedCollectionId = computed(() => this.collectionsStorage.selectedCollectionId());
    selectedRagType = signal<RagType | null>(null);

    filteredCollections = computed(() => {
        const search = this.filesSearchService.searchTerm().toLowerCase();
        const ragType = this.selectedRagType();
        return this.collections().filter((collection) => {
            const matchesSearch = collection.collection_name.toLowerCase().includes(search);
            const matchesRag = !ragType || collection.rag_configurations.some((r) => r.rag_type === ragType);
            return matchesSearch && matchesRag;
        });
    });

    /** Picking collections for a bulk export. */
    readonly selectMode = signal(false);
    private readonly checkedIds = signal<ReadonlySet<number>>(new Set());
    /**
     * The picked collections the list shows: one deleted meanwhile is not exported, and one the search or the RAG
     * filter hides is neither counted nor exported, so the export takes what the user sees. A hidden pick is kept
     * and counts again once the filter shows it.
     */
    readonly selectedIds = computed(() =>
        this.filteredCollections()
            .map((collection) => collection.collection_id)
            .filter((id) => this.checkedIds().has(id))
    );
    /** Collections whose export has not finished: their card's Export waits until it has. */
    readonly exportingIds = computed(() => this.transferExport.exportingCollectionIds());
    readonly allVisibleSelected = computed(() => {
        const visible = this.filteredCollections();
        return visible.length > 0 && visible.every((collection) => this.checkedIds().has(collection.collection_id));
    });

    /** Deleting the open collection takes the focus away with its panel: hand it to the card now in its place. */
    private readonly recoverFocusAfterRemoval = effect(() => {
        const ids = this.filteredCollections().map((collection) => collection.collection_id);
        untracked(() => {
            const removedIndex = this.shownCollectionIds.findIndex((id) => !ids.includes(id));
            this.shownCollectionIds = ids;
            if (removedIndex === -1) return;
            afterNextRender(() => this.focusCardIfFocusLost(removedIndex), { injector: this.injector });
        });
    });

    ragTypeItems: SelectItem[] = [
        { name: 'All', value: null },
        { name: 'Naive RAG', value: 'naive' },
        { name: 'Graph RAG', value: 'graph' },
        // { name: 'Hybrid RAG', value: 'hybrid' },
    ];

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;

    private readonly filesSearchService = inject(FilesSearchService);
    private readonly collectionsStorage = inject(CollectionsStorageService);
    private readonly transferExport = inject(TransferExportService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private shownCollectionIds: number[] = [];

    /** Opens the collection; in select mode, picks it instead. */
    onCollectionClick(id: number): void {
        if (this.selectMode()) {
            this.setChecked(id, !this.isChecked(id));
            return;
        }
        this.collectionsStorage.setSelectedCollectionId(id);
    }

    isChecked(id: number): boolean {
        return this.checkedIds().has(id);
    }

    setChecked(id: number, checked: boolean): void {
        const next = new Set(this.checkedIds());
        if (checked) {
            next.add(id);
        } else {
            next.delete(id);
        }
        this.checkedIds.set(next);
    }

    enterSelectMode(): void {
        this.selectMode.set(true);
    }

    exitSelectMode(): void {
        this.selectMode.set(false);
        this.checkedIds.set(new Set());
    }

    /** Picks every collection the list shows, or unpicks them when all are picked; hidden picks stay as they are. */
    toggleSelectAll(): void {
        const visibleIds = this.filteredCollections().map((collection) => collection.collection_id);
        const next = new Set(this.checkedIds());
        if (this.allVisibleSelected()) {
            visibleIds.forEach((id) => next.delete(id));
        } else {
            visibleIds.forEach((id) => next.add(id));
        }
        this.checkedIds.set(next);
    }

    // Exports are not tied to this list: one the user started still downloads after they leave the page.
    exportCollection(id: number): void {
        this.transferExport.exportCollections([id]).subscribe();
    }

    exportSelected(): void {
        const ids = this.selectedIds();
        if (ids.length === 0) return;
        this.exitSelectMode();
        this.transferExport.exportCollections(ids).subscribe();
    }

    private focusCardIfFocusLost(index: number): void {
        if (!isFocusLost(this.document)) return;
        const cards = this.collectionCards();
        cards[Math.min(index, cards.length - 1)]?.focus();
    }
}
