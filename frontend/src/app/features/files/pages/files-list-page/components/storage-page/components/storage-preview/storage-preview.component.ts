import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, BlobPreviewComponent, ButtonComponent, canPreviewFilePart } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { catchError, EMPTY, Observable, switchMap, tap } from 'rxjs';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageApiService } from '../../../../../../services/storage-api.service';

// The preview is rendered on the main thread; past this size only the beginning of a
// text-like file is fetched, and other types are not previewed at all.
const MAX_PREVIEW_FILE_SIZE = 5 * 1024 * 1024;
// How much of a larger text-like file is fetched: enough for the rows/characters the
// preview renders (see blob-preview), so the rest is never downloaded.
const PARTIAL_PREVIEW_BYTES = 1024 * 1024;

type PreviewMode = 'none' | 'full' | 'partial' | 'too-large';

function resolvePreviewMode(item: StorageItem | null): PreviewMode {
    if (!item || item.type === 'folder') return 'none';
    if ((item.size ?? 0) <= MAX_PREVIEW_FILE_SIZE) return 'full';
    return canPreviewFilePart(item.name) ? 'partial' : 'too-large';
}

@Component({
    selector: 'app-storage-preview',
    imports: [AppSvgIconComponent, BlobPreviewComponent, ButtonComponent, MatTooltipModule, HasPermissionDirective],
    templateUrl: './storage-preview.component.html',
    styleUrls: ['./storage-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoragePreviewComponent {
    item = input<StorageItem | null>(null);
    selectedItems = input<StorageItem[]>([]);
    showSidebar = input(true);
    content = input<string | null>(null);
    readOnly = input<boolean>(false);
    toggleSidebar = output<void>();
    contextAction = output<{ action: string; item: StorageItem; selectedItems?: StorageItem[] }>();
    breadcrumbClick = output<string>();

    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private permissionsService = inject(PermissionsService);

    previewBlob = signal<Blob | null>(null);
    isLoadingPreview = signal<boolean>(false);
    previewError = signal<string | null>(null);
    kebabMenuOpen = signal<boolean>(false);
    kebabMenuPosition = signal<{ right: number; top: number }>({ right: 0, top: 0 });
    readonly previewMode = computed(() => resolvePreviewMode(this.item()));

    constructor() {
        // switchMap drops the previous file's download, so a late answer can't land under the new file.
        toObservable(this.item)
            .pipe(
                switchMap((item) => this.loadPreview(item)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    get breadcrumbs(): string[] {
        const item = this.item();
        if (!item) return [];
        return item.path.split('/').filter(Boolean);
    }

    get hasFileSelected(): boolean {
        const item = this.item();
        return !!item && item.type === 'file';
    }

    get canDownload(): boolean {
        return this.permissionsService.can(ResourceCode.Files, ActionCode.Export);
    }

    onDownload(): void {
        const item = this.item();
        if (item) {
            this.contextAction.emit({ action: 'download', item });
        }
    }

    onKebabClick(event: MouseEvent): void {
        event.stopPropagation();
        const btn = event.currentTarget as HTMLElement;
        const rect = btn.getBoundingClientRect();
        this.kebabMenuPosition.set({ right: window.innerWidth - rect.right, top: rect.bottom + 4 });
        this.kebabMenuOpen.set(true);
    }

    closeKebabMenu(): void {
        this.kebabMenuOpen.set(false);
    }

    onKebabMenuAction(action: string): void {
        this.kebabMenuOpen.set(false);
        const item = this.item();
        if (!item) return;
        const selectedItems = this.selectedItems();
        if (action === 'download' && selectedItems.length > 1) {
            this.contextAction.emit({ action: 'download-selected', item, selectedItems });
        } else {
            this.contextAction.emit({ action, item });
        }
    }

    private loadPreview(currentItem: StorageItem | null): Observable<Blob> {
        const mode = resolvePreviewMode(currentItem);
        this.previewBlob.set(null);
        this.previewError.set(mode === 'too-large' ? 'File is too large to preview' : null);
        this.isLoadingPreview.set(mode === 'full' || mode === 'partial');

        if (!currentItem || !this.isLoadingPreview()) return EMPTY;

        return this.storageApiService
            .downloadBlob(currentItem.path, mode === 'partial' ? PARTIAL_PREVIEW_BYTES : undefined)
            .pipe(
                tap((blob) => {
                    this.previewBlob.set(blob);
                    this.isLoadingPreview.set(false);
                }),
                catchError(() => {
                    this.previewError.set('Failed to load file preview');
                    this.isLoadingPreview.set(false);
                    return EMPTY;
                })
            );
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
