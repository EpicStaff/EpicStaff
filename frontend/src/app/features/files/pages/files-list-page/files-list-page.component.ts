import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, effect, inject, untracked } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { NavigationEnd, PRIMARY_OUTLET, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AppSvgIconComponent, ButtonComponent, TabButtonComponent } from '@shared/components';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map, startWith } from 'rxjs';
import { switchMap } from 'rxjs/operators';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { CreateCollectionDialogComponent } from '../../../knowledge-sources/components/create-collection-dialog/create-collection-dialog.component';
import { CollectionsStorageService } from '../../../knowledge-sources/services/collections-storage.service';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../../components/create-folder-dialog/create-folder-dialog.component';
import { FilesSearchService } from '../../services/files-search.service';
import { StorageApiService } from '../../services/storage-api.service';

@Component({
    selector: 'app-files-list-page',
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        TabButtonComponent,
        ButtonComponent,
        FormsModule,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
    ],
    templateUrl: './files-list-page.component.html',
    styleUrls: ['./files-list-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [FilesSearchService],
})
export class FilesListPageComponent {
    private readonly dialog = inject(Dialog);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);
    private readonly storageApiService = inject(StorageApiService);
    private readonly collectionsStorageService = inject(CollectionsStorageService);
    private readonly toastService = inject(ToastService);
    private readonly permissionService = inject(PermissionsService);
    readonly filesSearchService = inject(FilesSearchService);

    public tabs = [
        {
            label: 'Knowledge Sources',
            link: 'knowledge-sources',
            isPermitted: () => this.permissionService.can(ResourceCode.KnowledgeSources, ActionCode.Read),
        },
        {
            label: 'Files',
            link: 'files',
            isPermitted: () => this.permissionService.can(ResourceCode.Files, ActionCode.Read),
        },
        {
            label: 'Key-Value Tables',
            link: 'key-value-tables',
            isPermitted: () => this.permissionService.can(ResourceCode.KeyValueTables, ActionCode.Read),
        },
    ];

    readonly searchTerm = this.filesSearchService.searchTerm;

    private readonly currentUrl = toSignal(
        this.router.events.pipe(
            filter((e) => e instanceof NavigationEnd),
            map((e) => (e as NavigationEnd).urlAfterRedirects),
            startWith(this.router.url)
        )
    );

    // The one search box means something different on each tab, so a term never carries over a tab switch.
    // The tab is the segment after `/storage`; a substring match would also hit the `path` query of the Files tab.
    private readonly activeTabLink = computed(() => {
        const url = this.currentUrl();
        if (!url) return null;
        const tabSegment = this.router.parseUrl(url).root.children[PRIMARY_OUTLET]?.segments[1]?.path;
        return this.tabs.find((tab) => tab.link === tabSegment)?.link ?? null;
    });
    // Key-Value Tables searches keys in its own grid header, next to "Add entry".
    readonly showSearch = computed(() => this.activeTabLink() !== 'key-value-tables');
    readonly clearSearchOnTabChange = effect(() => {
        this.activeTabLink();
        untracked(() => this.filesSearchService.clear());
    });

    activeTabBtn = computed(() => {
        const tabLink = this.activeTabLink();
        if (tabLink === 'files') {
            const canCreateFiles = this.permissionService.can(ResourceCode.Files, ActionCode.Create);
            return {
                label: 'Add files',
                permitted: canCreateFiles,
                action: () => this.onCreateFolderClick(),
            };
        }

        if (tabLink === 'knowledge-sources') {
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
