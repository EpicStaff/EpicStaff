import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { Component, inject, signal } from '@angular/core';
import { BulkDeleteItem, BulkDeletePreviewGroup, BulkDeletePreviewItem, BulkDeleteUsageLine } from '@shared/models';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';

export interface BulkDeleteDialogData {
    groups: BulkDeletePreviewGroup[];
}

/** Id of the title `h2`; `BulkDeleteService` passes this as the dialog's `ariaLabelledBy`
 *  so the dialog is announced by its title. */
export const BULK_DELETE_DIALOG_TITLE_ID = 'bulk-delete-dialog-title';

/** Plain rows a list shows before the rest collapse behind "Show N more". In-use and
 *  blocked rows are never collapsed — they are what the user must notice. */
const VISIBLE_PLAIN_ROWS = 5;

type CollapsibleList = 'deletable' | 'not-found';

@Component({
    selector: 'app-bulk-delete-dialog',
    imports: [DialogModule, AppSvgIconComponent, IconButtonComponent],
    templateUrl: './bulk-delete-dialog.component.html',
    styleUrls: ['./bulk-delete-dialog.component.scss'],
})
export class BulkDeleteDialogComponent {
    private readonly dialogRef = inject(DialogRef<boolean>);
    private readonly data = inject<BulkDeleteDialogData>(DIALOG_DATA);
    /** Keys (`<list>-<group index>`) of the lists the user expanded. */
    private readonly expandedLists = signal<ReadonlySet<string>>(new Set());

    protected readonly groups = this.data.groups;
    protected readonly totalDeletable = this.groups.reduce((sum, group) => sum + group.deletable.length, 0);
    protected readonly totalBlocked = this.groups.reduce((sum, group) => sum + group.blocked.length, 0);
    protected readonly totalItems = this.groups.reduce(
        (sum, group) => sum + group.deletable.length + group.blocked.length + group.notFound.length,
        0
    );
    protected readonly summaryText =
        this.totalBlocked > 0
            ? `${this.totalDeletable} of ${this.totalDeletable + this.totalBlocked} will be deleted. This can't be undone.`
            : "This can't be undone.";
    protected readonly isEmpty = this.totalDeletable === 0;
    protected readonly confirmText = this.totalDeletable > 1 ? `Delete ${this.totalDeletable}` : 'Delete';
    protected readonly title = this.buildTitle();
    /** True when the whole dialog has exactly one item and it has no usage — shown
     *  as a single plain line instead of repeating a one-item list. */
    protected readonly isSingleItemNoUsage =
        this.totalItems === 1 && this.totalDeletable === 1 && this.groups[0].deletable[0].usage.length === 0;
    protected readonly titleId = BULK_DELETE_DIALOG_TITLE_ID;

    protected onCancel(): void {
        this.dialogRef.close(false);
    }

    protected onConfirm(): void {
        this.dialogRef.close(true);
    }

    protected onClose(): void {
        this.dialogRef.close(false);
    }

    protected groupHeading(group: BulkDeletePreviewGroup): string {
        return capitalize(group.label.plural);
    }

    protected groupItemCount(group: BulkDeletePreviewGroup): number {
        return group.deletable.length + group.blocked.length + group.notFound.length;
    }

    protected groupHasUsage(group: BulkDeletePreviewGroup): boolean {
        return group.deletable.some((item) => item.usage.length > 0);
    }

    protected visibleDeletable(group: BulkDeletePreviewGroup, groupIndex: number): BulkDeletePreviewItem[] {
        if (this.isExpanded('deletable', groupIndex)) {
            return group.deletable;
        }
        let plainRowsShown = 0;
        return group.deletable.filter((item) => {
            if (item.usage.length > 0) {
                return true;
            }
            plainRowsShown += 1;
            return plainRowsShown <= VISIBLE_PLAIN_ROWS;
        });
    }

    protected hiddenDeletableCount(group: BulkDeletePreviewGroup): number {
        const plainRows = group.deletable.filter((item) => item.usage.length === 0).length;
        return Math.max(0, plainRows - VISIBLE_PLAIN_ROWS);
    }

    protected visibleNotFound(group: BulkDeletePreviewGroup, groupIndex: number): BulkDeleteItem[] {
        return this.isExpanded('not-found', groupIndex) ? group.notFound : group.notFound.slice(0, VISIBLE_PLAIN_ROWS);
    }

    protected hiddenNotFoundCount(group: BulkDeletePreviewGroup): number {
        return Math.max(0, group.notFound.length - VISIBLE_PLAIN_ROWS);
    }

    protected isExpanded(list: CollapsibleList, groupIndex: number): boolean {
        return this.expandedLists().has(`${list}-${groupIndex}`);
    }

    protected toggleList(list: CollapsibleList, groupIndex: number): void {
        const key = `${list}-${groupIndex}`;
        this.expandedLists.update((keys) => {
            const next = new Set(keys);
            if (next.has(key)) {
                next.delete(key);
            } else {
                next.add(key);
            }
            return next;
        });
    }

    protected toggleLabel(list: CollapsibleList, groupIndex: number, hiddenCount: number): string {
        return this.isExpanded(list, groupIndex) ? 'Show less' : `Show ${hiddenCount} more`;
    }

    protected usageLineText(line: BulkDeleteUsageLine): string {
        const more = line.hasMore ? ' and more' : '';
        return `Used in ${line.count} ${line.label}: ${line.sampleNames.join(', ')}${more}`;
    }

    private buildTitle(): string {
        if (this.totalItems === 1 && this.totalDeletable === 1) {
            return `Delete "${this.groups[0].deletable[0].name}"?`;
        }
        if (this.totalDeletable === 0) {
            return 'Nothing can be deleted';
        }
        if (this.groups.length === 1) {
            const label = this.totalDeletable === 1 ? this.groups[0].label.singular : this.groups[0].label.plural;
            return `Delete ${this.totalDeletable} ${label}?`;
        }
        return `Delete ${this.totalDeletable} items?`;
    }
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
