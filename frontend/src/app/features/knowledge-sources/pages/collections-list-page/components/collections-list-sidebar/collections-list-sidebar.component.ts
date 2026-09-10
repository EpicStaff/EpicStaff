import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ButtonComponent, SelectComponent, SelectItem } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

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
    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
