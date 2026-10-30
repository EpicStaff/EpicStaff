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
import { ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';

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
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionsListItemSidebarComponent {
    private readonly filesSearchService = inject(FilesSearchService);
    private readonly collectionsStorage = inject(CollectionsStorageService);

    collections = input<GetCollectionRequest[]>([]);
    selectedCollectionId = this.collectionsStorage.selectedCollectionId;

    selectCollection(id: number): void {
        this.collectionsStorage.setSelectedCollectionId(id);
    }

    ragTypeItems: SelectItem[] = [
        { name: 'All', value: null },
        { name: 'Naive RAG', value: 'naive' },
        { name: 'Graph RAG', value: 'graph' },
        // { name: 'Hybrid RAG', value: 'hybrid' },
    ];

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

    onCreateCollection = output();

    private readonly collectionCards = viewChildren(CollectionComponent);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private shownCollectionIds: number[] = [];

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

    private focusCardIfFocusLost(index: number): void {
        if (!isFocusLost(this.document)) return;
        const cards = this.collectionCards();
        cards[Math.min(index, cards.length - 1)]?.focus();
    }

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
