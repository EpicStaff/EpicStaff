import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { Component, inject, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { BulkDeletePreviewGroup, BulkDeleteUsageLine } from '@shared/models';
import { recycleBinNotice } from '@shared/utils';

import { AppIconComponent } from '../app-icon/app-icon.component';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons/button/button.component';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';
import { HintMessageComponent } from '../hint-message/hint-message.component';

export interface BulkDeleteDialogData {
    groups: BulkDeletePreviewGroup[];
}

/** Id of the title `h2`; `BulkDeleteService` passes this as the dialog's `ariaLabelledBy`
 *  so the dialog is announced by its title. */
export const BULK_DELETE_DIALOG_TITLE_ID = 'bulk-delete-dialog-title';

const BLOCKED_ROW_TOOLTIP = "Used somewhere you don't have access to.";

let nextDialogInstanceId = 0;

/** One line of a section's list. Blocked and in-use rows carry a label on the right and their details in a
 *  tooltip; plain rows are the name alone. */
interface BulkDeleteDialogRow {
    kind: 'blocked' | 'in-use' | 'plain';
    id: number;
    name: string;
    label: string | null;
    /** One detail per line. A row with a tooltip is focusable, so keyboard users can reach it. */
    tooltip: string | null;
}

/** A collapsible section: the selected items of one group, or those of them that were already deleted. */
interface BulkDeleteDialogSection {
    /** Unique on the page; also the id of the section's list, for the header's `aria-controls`. */
    id: string;
    kind: 'items' | 'not-found';
    title: string;
    count: number;
    rows: BulkDeleteDialogRow[];
}

@Component({
    selector: 'app-bulk-delete-dialog',
    imports: [
        DialogModule,
        MatTooltipModule,
        AppIconComponent,
        AppSvgIconComponent,
        ButtonComponent,
        IconButtonComponent,
        HintMessageComponent,
    ],
    templateUrl: './bulk-delete-dialog.component.html',
    styleUrls: ['./bulk-delete-dialog.component.scss'],
})
export class BulkDeleteDialogComponent {
    // `data` must stay above the fields below: they read it in their initializers.
    private readonly dialogRef = inject(DialogRef<boolean>);
    private readonly data = inject<BulkDeleteDialogData>(DIALOG_DATA);
    private readonly groups = this.data.groups;

    protected readonly sections = this.buildSections();
    /** Item sections start open; "Already deleted" sections start closed. */
    private readonly openSectionIds = signal<ReadonlySet<string>>(
        new Set(this.sections.filter((section) => section.kind === 'items').map((section) => section.id))
    );

    // Private, but kept here: the summary, title and flags below read them in their initializers.
    private readonly totalDeletable = this.groups.reduce((sum, group) => sum + group.deletable.length, 0);
    private readonly totalBlocked = this.groups.reduce((sum, group) => sum + group.blocked.length, 0);
    private readonly totalItems = this.groups.reduce(
        (sum, group) => sum + group.deletable.length + group.blocked.length + group.notFound.length,
        0
    );
    protected readonly summaryText = this.buildSummaryText();
    protected readonly isEmpty = this.totalDeletable === 0;
    protected readonly title = this.buildTitle();
    /** True when the whole dialog has exactly one item and it has no usage — shown
     *  as a single plain line instead of repeating a one-item list. */
    protected readonly isSingleItemNoUsage =
        this.totalItems === 1 && this.totalDeletable === 1 && this.groups[0].deletable[0].usage.length === 0;
    /** Some item that will be deleted is used somewhere: one banner says what happens to those references. */
    protected readonly hasItemInUse = this.groups.some((group) =>
        group.deletable.some((item) => item.usage.length > 0)
    );
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

    protected isSectionOpen(section: BulkDeleteDialogSection): boolean {
        return this.openSectionIds().has(section.id);
    }

    protected toggleSection(section: BulkDeleteDialogSection): void {
        this.openSectionIds.update((ids) => {
            const next = new Set(ids);
            if (next.has(section.id)) {
                next.delete(section.id);
            } else {
                next.add(section.id);
            }
            return next;
        });
    }

    /** The selected items of every group first, then the "Already deleted" sections, in group order. */
    private buildSections(): BulkDeleteDialogSection[] {
        const idPrefix = `bulk-delete-dialog-${nextDialogInstanceId++}`;
        const isSingleGroup = this.groups.length === 1;

        const itemSections = this.groups.flatMap((group, groupIndex): BulkDeleteDialogSection[] => {
            const itemCount = group.deletable.length + group.blocked.length;
            if (itemCount === 0) return [];
            return [
                {
                    id: `${idPrefix}-items-${groupIndex}`,
                    kind: 'items',
                    title: capitalize(group.label.plural),
                    count: itemCount,
                    rows: buildItemRows(group),
                },
            ];
        });
        const notFoundSections = this.groups.flatMap((group, groupIndex): BulkDeleteDialogSection[] => {
            if (group.notFound.length === 0) return [];
            return [
                {
                    id: `${idPrefix}-not-found-${groupIndex}`,
                    kind: 'not-found',
                    title: isSingleGroup ? 'Already deleted' : `Already deleted ${group.label.plural}`,
                    count: group.notFound.length,
                    rows: group.notFound.map((item) => plainRow(item.id, item.name)),
                },
            ];
        });
        return [...itemSections, ...notFoundSections];
    }

    private buildSummaryText(): string {
        const consequence = this.buildConsequenceText();
        return this.totalBlocked > 0
            ? `${this.totalDeletable} of ${this.totalDeletable + this.totalBlocked} will be deleted. ${consequence}`
            : consequence;
    }

    /** The recycle-bin notice only when every group that has something to delete is a recycle-bin
     *  group; otherwise (mixed or permanent) the safe "can't be undone" wording. */
    private buildConsequenceText(): string {
        const deletableGroups = this.groups.filter((group) => group.deletable.length > 0);
        const recycleBin = deletableGroups[0]?.recycleBin;
        if (recycleBin && deletableGroups.every((group) => group.recycleBin !== undefined)) {
            return recycleBinNotice(recycleBin.retentionDays, this.totalDeletable);
        }
        return "This can't be undone.";
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

/** Blocked rows first, then in-use rows, then the rest: the list scrolls, and the scroll must never
 *  hide the rows the user has to notice. */
function buildItemRows(group: BulkDeletePreviewGroup): BulkDeleteDialogRow[] {
    const blocked = group.blocked.map(
        (item): BulkDeleteDialogRow => ({
            kind: 'blocked',
            id: item.id,
            name: item.name,
            label: 'Will not be deleted',
            tooltip: BLOCKED_ROW_TOOLTIP,
        })
    );
    const inUse = group.deletable
        .filter((item) => item.usage.length > 0)
        .map(
            (item): BulkDeleteDialogRow => ({
                kind: 'in-use',
                id: item.id,
                name: item.name,
                label: 'In use',
                tooltip: item.usage.map(usageLineText).join('\n'),
            })
        );
    const plain = group.deletable.filter((item) => item.usage.length === 0).map((item) => plainRow(item.id, item.name));
    return [...blocked, ...inUse, ...plain];
}

function plainRow(id: number, name: string): BulkDeleteDialogRow {
    return { kind: 'plain', id, name, label: null, tooltip: null };
}

function usageLineText(line: BulkDeleteUsageLine): string {
    const more = line.hasMore ? ' and more' : '';
    return `Used in ${line.count} ${line.label}: ${line.sampleNames.join(', ')}${more}`;
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
