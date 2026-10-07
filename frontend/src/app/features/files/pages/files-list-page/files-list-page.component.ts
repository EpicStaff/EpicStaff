import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    linkedSignal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, SpinnerComponent, TabButtonComponent } from '@shared/components';
import { DragHoverDirective, HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map, startWith } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { KeyValueTablesPageComponent } from '../../../key-value-tables/pages/key-value-tables-page/key-value-tables-page.component';
import { CreateCollectionDialogComponent } from '../../../knowledge-sources/components/create-collection-dialog/create-collection-dialog.component';
import { CollectionsListPageComponent } from '../../../knowledge-sources/pages/collections-list-page/collections-list-page.component';
import { CollectionsStorageService } from '../../../knowledge-sources/services/collections-storage.service';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../../components/create-folder-dialog/create-folder-dialog.component';
import { FILES_TAB, FilesTab } from '../../constants/files-tabs';
import { FilesSearchService } from '../../services/files-search.service';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageDragService } from '../../services/storage-drag.service';
import { StoragePageComponent } from './components/storage-page/storage-page.component';

/** How long a storage drag has to rest on a tab before the tab opens. */
export const TAB_SPRING_LOAD_DELAY_MS = 500;

interface FilesTabConfig {
    label: string;
    link: FilesTab;
    isPermitted: () => boolean;
}

/**
 * Tab shell for `/storage`. It renders the tab pages itself instead of through a
 * `<router-outlet>` (the child routes are component-less and only own URL + guards), so the
 * Storage page — the source of a storage drag — can stay mounted, visually hidden, while the
 * user drags onto Knowledge Sources. A router outlet would destroy it and lose the drag.
 */
@Component({
    selector: 'app-files-list-page',
    imports: [
        RouterLink,
        RouterLinkActive,
        TabButtonComponent,
        ButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
        DragHoverDirective,
        SpinnerComponent,
        CollectionsListPageComponent,
        StoragePageComponent,
        KeyValueTablesPageComponent,
    ],
    templateUrl: './files-list-page.component.html',
    styleUrls: ['./files-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [FilesSearchService],
})
export class FilesListPageComponent {
    private readonly dialog = inject(Dialog);
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly destroyRef = inject(DestroyRef);
    private readonly storageApiService = inject(StorageApiService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly toastService = inject(ToastService);
    private readonly permissionService = inject(PermissionsService);
    protected readonly storageDrag = inject(StorageDragService);
    readonly filesSearchService = inject(FilesSearchService);

    readonly tabs: FilesTabConfig[] = [
        {
            label: 'Knowledge Sources',
            link: FILES_TAB.KnowledgeSources,
            isPermitted: () => this.permissionService.can(ResourceCode.KnowledgeSources, ActionCode.Read),
        },
        {
            label: 'Files',
            link: FILES_TAB.Storage,
            isPermitted: () => this.permissionService.can(ResourceCode.Files, ActionCode.Read),
        },
        {
            label: 'Key-Value Tables',
            link: FILES_TAB.KeyValueTables,
            isPermitted: () => this.permissionService.can(ResourceCode.KeyValueTables, ActionCode.Read),
        },
    ];

    readonly searchTerm = this.filesSearchService.searchTerm;

    /** The tab whose (component-less) child route is active; the guards already vetted it. */
    protected readonly activeTab = toSignal(
        this.router.events.pipe(
            filter((event) => event instanceof NavigationEnd),
            map(() => this.readActiveTab()),
            startWith(this.readActiveTab())
        ),
        { requireSync: true }
    );

    protected readonly isKnowledgeSourcesActive = computed(() => this.activeTab() === FILES_TAB.KnowledgeSources);
    protected readonly isStorageActive = computed(() => this.activeTab() === FILES_TAB.Storage);
    protected readonly isKeyValueTablesActive = computed(() => this.activeTab() === FILES_TAB.KeyValueTables);

    /** Key-Value Tables searches keys in its own grid header, next to "Add entry". */
    protected readonly showSearch = computed(() => !this.isKeyValueTablesActive());

    /**
     * The Storage page is rendered while its tab is active, and kept mounted after a tab switch
     * for as long as a storage drag that started there is live — it holds the drag source row,
     * whose `dragend` ends the drag. A drag never mounts it: it can only extend a mount.
     */
    protected readonly isStorageRendered = linkedSignal<{ isActive: boolean; isDragging: boolean }, boolean>({
        source: () => ({ isActive: this.isStorageActive(), isDragging: this.storageDrag.isDragging() }),
        computation: ({ isActive, isDragging }, previous) => isActive || (isDragging && (previous?.value ?? false)),
    });

    protected readonly tabSpringLoadDelay = TAB_SPRING_LOAD_DELAY_MS;

    /** The one search box means something different on each tab, so a term never carries over a tab switch. */
    private readonly clearSearchOnTabChange = effect(() => {
        this.activeTab();
        untracked(() => this.filesSearchService.clear());
    });

    readonly activeTabBtn = computed(() => {
        const activeTab = this.activeTab();
        if (activeTab === FILES_TAB.Storage) {
            const canCreateFiles = this.permissionService.can(ResourceCode.Files, ActionCode.Create);
            return {
                label: 'Add files',
                permitted: canCreateFiles,
                action: () => this.onCreateFolderClick(),
            };
        }

        if (activeTab === FILES_TAB.KnowledgeSources) {
            const canCreateCollection = this.permissionService.can(ResourceCode.KnowledgeSources, ActionCode.Create);
            const canUpdateCollection = this.permissionService.can(ResourceCode.KnowledgeSources, ActionCode.Update);
            return {
                label: 'Add collection',
                permitted: canCreateCollection && canUpdateCollection,
                action: () => this.onCreateCollectionClick(),
            };
        }

        return;
    });

    /** Spring-loaded tab: a storage drag resting on another tab opens it. */
    onTabDragHover(tab: FilesTabConfig): void {
        if (!this.storageDrag.isDragging() || !tab.isPermitted() || this.activeTab() === tab.link) return;
        void this.router.navigate([tab.link], { relativeTo: this.route });
    }

    public onCreateFolderClick(): void {
        const dialogRef = this.dialog.open<CreateFolderDialogResult>(CreateFolderDialogComponent);

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            if (result.type === 'mkdir') this.toastService.success(`Folder "${result.path}" created`);
            if (result.type === 'upload' && result.count) this.toastService.success(`${result.count} file(s) uploaded`);
            this.storageApiService.triggerRefresh();
        });
    }

    public onCreateCollectionClick(): void {
        this.collectionsStorageService
            .createCollection()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ collection_id }) => {
                    if (!collection_id) return;
                    this.collectionsStorageService.setSelectedCollectionId(collection_id);
                    this.openCreateCollectionModal(collection_id);
                },
                error: () => this.toastService.error('Failed to create collection'),
            });
    }

    private readActiveTab(): FilesTab | null {
        // `routeConfig` (not `snapshot`): the child snapshot is not set yet while this page is being activated.
        const path = this.route.firstChild?.routeConfig?.path;
        return this.tabs.find((tab) => tab.link === path)?.link ?? null;
    }

    private openCreateCollectionModal(collectionId: number): void {
        const dialogRef = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id: collectionId },
            disableClose: true,
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => this.collectionsStorageService.getFullCollection(collectionId, true))
            )
            .subscribe({
                error: () => this.toastService.error('Failed to get collection data'),
            });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
