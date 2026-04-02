import { ChangeDetectionStrategy, Component, computed, input, model, output, signal } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ButtonComponent, SearchComponent, SelectComponent } from '@shared/components';

import { GetCollectionRequest } from '../../../../models/collection.model';
import { CollectionComponent } from './collection/collection.component';

@Component({
    selector: 'app-collections-list-sidebar',
    templateUrl: './collections-list-sidebar.component.html',
    styleUrls: ['./collections-list-sidebar.component.scss'],
    imports: [ButtonComponent, ReactiveFormsModule, FormsModule, CollectionComponent, SearchComponent, SelectComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionsListItemSidebarComponent {
    searchTerm = signal<string>('');
    collections = input<GetCollectionRequest[]>([]);

    filteredCollections = computed(() => {
        return this.collections().filter((collection) => {
            const search = this.searchTerm().toLowerCase();
            const collectionName = collection.collection_name.toLowerCase();
            return collectionName.includes(search);
        });
    });

    selectedCollectionId = model<number | null>();

    onCreateCollection = output();
}
