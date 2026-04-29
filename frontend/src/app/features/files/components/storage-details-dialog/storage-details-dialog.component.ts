import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog';
import { StorageGraph, StorageItemInfo } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';

interface StorageDetailsDialogData extends StorageItemInfo {
    usedIn?: StorageGraph[];
}

@Component({
    selector: 'app-storage-details-dialog',
    standalone: true,
    imports: [AppSvgIconComponent],
    templateUrl: './storage-details-dialog.component.html',
    styleUrls: ['./storage-details-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StorageDetailsDialogComponent {
    readonly dialogRef = inject(DialogRef<void>);
    readonly data = inject<StorageDetailsDialogData>(DIALOG_DATA);
    private readonly destroyRef = inject(DestroyRef);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly storageApiService = inject(StorageApiService);

    readonly usedInFlowsSignal = signal<StorageGraph[]>(this.data.usedIn ?? []);

    get modifiedAt(): string {
        return this.formatDate(this.data.modified);
    }

    get usedInFlows(): StorageGraph[] {
        return this.usedInFlowsSignal();
    }

    get title(): string {
        return this.data.type === 'folder' ? 'Folder Details' : 'File Details';
    }

    get typeLabel(): string {
        if (this.data.type === 'folder') {
            return 'folder';
        }
        const ext = this.data.name?.split('.').pop()?.toLowerCase();
        return ext || 'file';
    }

    get sizeLabel(): string {
        const size = this.data.size ?? 0;
        if (size >= 1024 * 1024) {
            return `${(size / (1024 * 1024)).toFixed(1)} MB`;
        }
        if (size >= 1024) {
            return `${Math.round(size / 1024)} KB`;
        }
        return `${size} B`;
    }

    get storagePath(): string {
        const path = this.data.path?.replace(/^\/+/, '') ?? '';
        return path;
    }

    async copyPath(): Promise<void> {
        try {
            await navigator.clipboard.writeText(this.storagePath);
        } catch {
            // no-op
        }
    }

    close(): void {
        this.dialogRef.close();
    }

    onRemoveFromFlow(graph: StorageGraph): void {
        const itemType = this.data.type === 'folder' ? 'folder' : 'file';
        const itemTitle = this.data.type === 'folder' ? 'Remove Folder?' : 'Remove File?';
        const itemName = this.escapeHtml(this.data.name ?? 'item');
        const safeFlowName = this.escapeHtml(graph.name);

        this.confirmationDialogService
            .confirm({
                title: itemTitle,
                message: `Are you sure you want to remove <strong>${itemName}</strong> ${itemType} from the <strong>${safeFlowName}</strong> flow?`,
                confirmText: 'Remove',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) {
                    return;
                }

                this.storageApiService
                    .removeFromGraph([this.data.path ?? ''], [graph.id])
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.usedInFlowsSignal.update((flows) => flows.filter((f) => f.id !== graph.id));
                        },
                    });
            });
    }

    private formatDate(value?: string): string {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}
