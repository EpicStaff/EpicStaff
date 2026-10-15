import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
    BULK_DELETE_MAX_IDS,
    BulkDeleteGroup,
    BulkDeleteOutcome,
    BulkDeletePreviewGroup,
    BulkDeleteResponse,
} from '@shared/models';
import { buildBulkDeletePreview, extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, forkJoin, map, Observable, of, switchMap } from 'rxjs';

import { ToastService } from '../../../services/notifications';
// Relative import, not the `@shared/components` barrel: `shared/services` importing the
// `@shared/components` barrel would create a `@shared/services` <-> `@shared/components` barrel
// cycle (19 shared components already import `@shared/services`).
import {
    BULK_DELETE_DIALOG_TITLE_ID,
    BulkDeleteDialogComponent,
} from '../../components/bulk-delete-dialog/bulk-delete-dialog.component';

/** A group paired with the dry-run response for its ids. */
interface GroupPreview {
    group: BulkDeleteGroup;
    response: BulkDeleteResponse;
}

@Injectable({
    providedIn: 'root',
})
export class BulkDeleteService {
    private readonly dialog = inject(Dialog);
    private readonly toast = inject(ToastService);

    run(groups: BulkDeleteGroup[]): Observable<BulkDeleteOutcome[]> {
        const nonEmptyGroups = groups.filter((group) => group.items.length > 0);
        if (nonEmptyGroups.length === 0) return EMPTY;

        if (nonEmptyGroups.some((group) => group.items.length > BULK_DELETE_MAX_IDS)) {
            this.toast.warning('You can delete up to 500 items at once.');
            return EMPTY;
        }

        return forkJoin(
            nonEmptyGroups.map((group) =>
                group.target
                    .previewBulkDelete(group.items.map((item) => item.id))
                    .pipe(map((response): GroupPreview => ({ group, response })))
            )
        ).pipe(
            catchError((error: unknown) => {
                this.reportPreviewError(error);
                return EMPTY;
            }),
            switchMap((previews) => this.confirmAndDelete(previews))
        );
    }

    private confirmAndDelete(previews: GroupPreview[]): Observable<BulkDeleteOutcome[]> {
        for (const preview of previews) {
            if (preview.response.not_found_ids.length > 0) {
                preview.group.target.removeFromCache(preview.response.not_found_ids);
            }
        }

        const previewGroups: BulkDeletePreviewGroup[] = previews.map((preview) =>
            buildBulkDeletePreview(preview.group, preview.response)
        );
        const totalDeletable = previewGroups.reduce((sum, previewGroup) => sum + previewGroup.deletable.length, 0);

        const dialogRef = this.dialog.open<boolean>(BulkDeleteDialogComponent, {
            width: '485px',
            data: { groups: previewGroups },
            ariaLabelledBy: BULK_DELETE_DIALOG_TITLE_ID,
        });

        return dialogRef.closed.pipe(
            switchMap((result) => {
                if (result !== true || totalDeletable === 0) return EMPTY;
                return this.deleteConfirmed(previews);
            })
        );
    }

    private deleteConfirmed(previews: GroupPreview[]): Observable<BulkDeleteOutcome[]> {
        const toDelete = previews.filter((preview) => preview.response.deletable_ids.length > 0);
        const requested = toDelete.reduce((sum, preview) => sum + preview.response.deletable_ids.length, 0);
        // Per-group requested count, used to size a whole-group request error when it has no
        // per-id response of its own (see showResultToast).
        const requestedByGroup = new Map(
            toDelete.map((preview): [BulkDeleteGroup, number] => [preview.group, preview.response.deletable_ids.length])
        );
        const label = this.resultNoun(previews, requested);

        return forkJoin(
            toDelete.map((preview) =>
                preview.group.target.bulkDelete(preview.response.deletable_ids).pipe(
                    map((response): BulkDeleteOutcome => ({ group: preview.group, response })),
                    catchError((error: unknown) => of<BulkDeleteOutcome>({ group: preview.group, error }))
                )
            )
        ).pipe(
            map((outcomes) => {
                this.showResultToast(outcomes, requestedByGroup, requested, label);
                return outcomes;
            })
        );
    }

    private reportPreviewError(error: unknown): void {
        if (error instanceof HttpErrorResponse) {
            if (error.status === 403) return;
            this.toast.error(extractHttpErrorMessage(error, 'Could not check what can be deleted.'));
            return;
        }
        this.toast.error('Could not check what can be deleted.');
    }

    private resultNoun(previews: GroupPreview[], count: number): string {
        if (previews.length === 1) {
            const { label } = previews[0].group;
            return count === 1 ? label.singular : label.plural;
        }
        return count === 1 ? 'item' : 'items';
    }

    /**
     * `done` = actually deleted (`deleted_count`) + already gone by the time of the real delete
     * (`not_found_ids` on that response — it vanished between preview and confirm, e.g. a second
     * dialog confirmed after the first one already deleted it). `failed` = `skipped` on the real
     * response + the requested count of any group whose real-delete request errored outright
     * (no per-id outcome for it).
     */
    private showResultToast(
        outcomes: BulkDeleteOutcome[],
        requestedByGroup: ReadonlyMap<BulkDeleteGroup, number>,
        requested: number,
        noun: string
    ): void {
        const errors = outcomes.filter((outcome) => outcome.error !== undefined);

        const deleted = outcomes.reduce((sum, outcome) => sum + (outcome.response?.deleted_count ?? 0), 0);
        const alreadyGone = outcomes.reduce((sum, outcome) => sum + (outcome.response?.not_found_ids.length ?? 0), 0);
        const skipped = outcomes.reduce((sum, outcome) => sum + (outcome.response?.skipped.length ?? 0), 0);
        const erroredItems = errors.reduce((sum, outcome) => sum + (requestedByGroup.get(outcome.group) ?? 0), 0);

        const done = deleted + alreadyGone;
        const failed = skipped + erroredItems;

        if (failed === 0) {
            this.toast.success(deleted === 0 && done > 0 ? 'Already deleted.' : `Deleted ${deleted} ${noun}.`);
            return;
        }

        if (done > 0) {
            this.toast.warning(`Deleted ${deleted} of ${requested} ${noun}. ${failed} couldn't be deleted.`);
            return;
        }

        const singleError = errors.length === 1 ? errors[0].error : undefined;
        if (singleError instanceof HttpErrorResponse && singleError.status === 403) return;

        if (errors.length === 1) {
            const message =
                singleError instanceof HttpErrorResponse
                    ? extractHttpErrorMessage(singleError, 'Failed to delete.')
                    : 'Failed to delete.';
            this.toast.error(message);
            return;
        }
        this.toast.error('Nothing was deleted.');
    }
}
