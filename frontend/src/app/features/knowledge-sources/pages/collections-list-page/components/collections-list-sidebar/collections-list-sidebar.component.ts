import { ChangeDetectionStrategy, Component, computed, inject, input, model, output, signal } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ButtonComponent, SelectComponent, SelectItem } from '@shared/components';

import { FilesSearchService } from '../../../../../files/services/files-search.service';
import { RagType } from '../../../../models/base-rag.model';
import { GetCollectionRequest } from '../../../../models/collection.model';
import { CollectionComponent } from './collection/collection.component';

@Component({
    selector: 'app-collections-list-sidebar',
    templateUrl: './collections-list-sidebar.component.html',
    styleUrls: ['./collections-list-sidebar.component.scss'],
    imports: [ButtonComponent, ReactiveFormsModule, FormsModule, CollectionComponent, SelectComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionsListItemSidebarComponent {
    private readonly filesSearchService = inject(FilesSearchService);

    collections = input<GetCollectionRequest[]>([]);

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

    selectedCollectionId = model<number | null>();

    onCreateCollection = output();
}
