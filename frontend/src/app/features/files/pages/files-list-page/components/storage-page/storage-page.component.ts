import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { DragDropAreaComponent, SpinnerComponent } from '@shared/components';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';

import { StorageItem } from '../../../../models/storage.models';
import { FilesSearchService } from '../../../../services/files-search.service';
import { StorageContextActionEvent, StorageTreeFacade } from '../../../../services/storage-tree-facade.service';
import { filterStorageItems } from '../../../../utils/storage-file.utils';
import { StoragePreviewComponent } from './components/storage-preview/storage-preview.component';
import { StorageTreeComponent } from './components/storage-tree/storage-tree.component';

const SIDEBAR_STORAGE_KEY = 'files';

@Component({
    selector: 'app-storage-page',
    imports: [
        StorageTreeComponent,
        StoragePreviewComponent,
        SpinnerComponent,
        DragDropAreaComponent,
        ResizableSidebarDirective,
    ],
    templateUrl: './storage-page.component.html',
    styleUrls: ['./storage-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [StorageTreeFacade],
})
export class StoragePageComponent {
    private readonly storageTree = viewChild(StorageTreeComponent);
    private readonly sidebarEl = viewChild<ElementRef<HTMLElement>>('sidebarEl');

    private destroyRef = inject(DestroyRef);
    private filesSearchService = inject(FilesSearchService);
    private route = inject(ActivatedRoute);
    private readonly sidebarWidthService = inject(SidebarWidthService);

    readonly facade = inject(StorageTreeFacade);

    private pendingDeepLinkPath: string | null = null;

    readonly showSidebar = signal<boolean>(true);

    protected readonly sidebarStorageKey = SIDEBAR_STORAGE_KEY;
    protected readonly sidebarWidth = this.sidebarWidthService.getWidth(SIDEBAR_STORAGE_KEY);

    protected readonly sidebarTargetElement = computed(() => this.sidebarEl()?.nativeElement);

    readonly filteredTreeData = computed(() =>
        filterStorageItems(this.facade.treeData(), this.filesSearchService.searchTerm())
    );

    readonly onOpenCreateFolder = (folderPath: string): void => {
        this.facade.openCreateFolderDialog(folderPath);
    };

    constructor() {
        this.pendingDeepLinkPath = this.route.snapshot.queryParamMap.get('path');

        this.facade.afterTreeLoad = () => {
            if (this.pendingDeepLinkPath) {
                const path = this.pendingDeepLinkPath;
                this.pendingDeepLinkPath = null;
                this.facade.expandAndSelectPath(path);
            }
        };

        this.facade.selectInTree
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((item) => this.storageTree()?.selectItemExternally(item));

        this.facade.init({ watchRefreshTick: true });
    }

    toggleSidebar(): void {
        this.showSidebar.update((v) => !v);
    }

    onFileSelect(item: StorageItem): void {
        this.facade.selectedFile.set(item);
    }

    onFolderSelect(item: StorageItem): void {
        this.facade.selectedFile.set(item);
    }

    onPreviewContextAction(event: StorageContextActionEvent): void {
        if (event.action === 'rename') {
            if (!this.showSidebar()) {
                this.showSidebar.set(true);
                setTimeout(() => this.storageTree()?.startRename(event.item));
            } else {
                this.storageTree()?.startRename(event.item);
            }
        } else {
            this.facade.onContextAction(event);
        }
    }
}
