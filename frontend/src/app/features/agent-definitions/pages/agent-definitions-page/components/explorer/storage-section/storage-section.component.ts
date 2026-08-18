import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    output,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { StorageItem } from '../../../../../../files/models/storage.models';
import { StorageTreeComponent } from '../../../../../../files/pages/files-list-page/components/storage-page/components/storage-tree/storage-tree.component';
import { StorageTreeFacade } from '../../../../../../files/services/storage-tree-facade.service';

@Component({
    selector: 'app-storage-section',
    imports: [StorageTreeComponent],
    templateUrl: './storage-section.component.html',
    styleUrls: ['./storage-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StorageSectionComponent implements OnInit {
    private readonly destroyRef: DestroyRef = inject(DestroyRef);

    readonly facade: StorageTreeFacade = inject(StorageTreeFacade);

    private readonly tree = viewChild(StorageTreeComponent);

    selectItem = output<StorageItem>();

    // TODO(EST-2946): storage search deferred — the tree shows unfiltered data for now.
    readonly items = computed(() => this.facade.treeData());

    ngOnInit(): void {
        this.facade.selectInTree
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((item) => this.tree()?.selectItemExternally(item));

        this.facade.loadTree();
    }

    onItemSelected(item: StorageItem): void {
        this.selectItem.emit(item);
    }

    openCreateFolder(): void {
        this.facade.openCreateFolderDialog('');
    }

    openMoreMenu(event: MouseEvent): void {
        this.tree()?.onMoreOptionsClick(event);
    }

    startRename(item: StorageItem): void {
        this.tree()?.startRename(item);
    }

    restoreSelection(item: StorageItem): void {
        this.tree()?.selectItemExternally(item);
    }
}
