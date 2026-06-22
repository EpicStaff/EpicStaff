import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { BlobPreviewComponent } from '../../../../../../../../shared/components/blob-preview/blob-preview.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageApiService } from '../../../../../../services/storage-api.service';

@Component({
    selector: 'app-storage-preview',
    imports: [AppSvgIconComponent, BlobPreviewComponent, ButtonComponent],
    templateUrl: './storage-preview.component.html',
    styleUrls: ['./storage-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoragePreviewComponent {
    item = input<StorageItem | null>(null);
    selectedItems = input<StorageItem[]>([]);
    showSidebar = input(true);
    toggleSidebar = output<void>();
    contextAction = output<{ action: string; item: StorageItem; selectedItems?: StorageItem[] }>();
    breadcrumbClick = output<string>();

    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);

    previewBlob = signal<Blob | null>(null);
    isLoadingPreview = signal<boolean>(false);
    previewError = signal<string | null>(null);
    kebabMenuOpen = signal<boolean>(false);
    kebabMenuPosition = signal<{ right: number; top: number }>({ right: 0, top: 0 });

    constructor() {
        effect(() => {
            this.loadPreview(this.item());
        });
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

    onDownload(): void {
        const item = this.item();
        if (item) {
            this.storageApiService.download(item.path);
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

    private loadPreview(currentItem: StorageItem | null): void {
        this.previewBlob.set(null);
        this.previewError.set(null);

        if (!currentItem || currentItem.type === 'folder') {
            this.isLoadingPreview.set(false);
            return;
        }

        this.isLoadingPreview.set(true);
        this.storageApiService
            .downloadBlob(currentItem.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => {
                    this.previewBlob.set(blob);
                    this.isLoadingPreview.set(false);
                },
                error: () => {
                    this.previewError.set('Failed to load file preview');
                    this.isLoadingPreview.set(false);
                },
            });
    }
}
