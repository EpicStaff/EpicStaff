import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    signal,
    viewChild,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, AuthorshipDetailsComponent, ConfirmationDialogService } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode, UserSummary } from '@shared/models';
import { isFocusLost } from '@shared/utils';

import { FileSizePipe } from '../../../../shared/pipes/file-size.pipe';
import { StorageGraph, StorageItemInfo } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';

interface StorageDetailsDialogData extends StorageItemInfo {
    usedIn?: StorageGraph[];
}

@Component({
    selector: 'app-storage-details-dialog',
    imports: [AppSvgIconComponent, AuthorshipDetailsComponent, MatTooltipModule, FileSizePipe, HasPermissionDirective],
    templateUrl: './storage-details-dialog.component.html',
    styleUrls: ['./storage-details-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StorageDetailsDialogComponent {
    private readonly closeButton = viewChild.required<ElementRef<HTMLButtonElement>>('closeButton');
    private readonly removeButtons = viewChildren<ElementRef<HTMLButtonElement>>('removeButton');

    readonly dialogRef = inject(DialogRef<void>);
    readonly data = inject<StorageDetailsDialogData>(DIALOG_DATA);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly storageApiService = inject(StorageApiService);

    readonly usedInFlowsSignal = signal<StorageGraph[]>(this.data.usedIn ?? []);

    // `/storage/info/` always sends the authorship fields, but the shared storage item type keeps them
    // optional; a missing value is rendered like a null one (the shared block shows "—").
    protected readonly owner: UserSummary | null = this.data.created_by ?? null;
    protected readonly createdAt: string | null = this.data.created_at ?? null;
    protected readonly lastEditor: UserSummary | null = this.data.last_edited_by ?? null;
    protected readonly lastEditedAt: string | null = this.data.last_edited_at ?? null;

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

    get sizeBytes(): number {
        return this.data.size ?? 0;
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
                            const removedIndex = this.usedInFlows.findIndex((flow) => flow.id === graph.id);
                            this.usedInFlowsSignal.update((flows) => flows.filter((f) => f.id !== graph.id));
                            this.keepFocusAfterRemoval(removedIndex);
                        },
                    });
            });
    }

    /**
     * The removed chip takes its focused Remove button along, which would drop the focus out of the dialog. It moves to
     * the Remove button now in that place (or the last one), or to Close once no flow is left. Focus the user moved
     * elsewhere meanwhile stays where it is.
     */
    private keepFocusAfterRemoval(index: number): void {
        afterNextRender(
            () => {
                if (!isFocusLost(this.document)) return;
                const buttons = this.removeButtons();
                const next = buttons[Math.min(index, buttons.length - 1)];
                (next ?? this.closeButton()).nativeElement.focus();
            },
            { injector: this.injector }
        );
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

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
