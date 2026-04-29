import { ChangeDetectionStrategy, Component, computed, inject, input, model, output } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ButtonComponent, SelectComponent } from '@shared/components';

import { FilesSearchService } from '../../../../../../features/files/services/files-search.service';
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

    filteredCollections = computed(() => {
        const search = this.filesSearchService.searchTerm().toLowerCase();
        return this.collections().filter((collection) => collection.collection_name.toLowerCase().includes(search));
    });

    selectedCollectionId = model<number | null>();

    onCreateCollection = output();
}
