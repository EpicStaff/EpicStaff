import { inject, Injectable } from '@angular/core';
import { ExportEntityLabels, ExportOptions } from '@shared/models';
import { escapeHtml, pluralize } from '@shared/utils';
import { Observable } from 'rxjs';
import { filter, map } from 'rxjs/operators';

// Relative import, not the `@shared/components` barrel: shared components import `@shared/services`, so the barrel
// would make a `@shared/services` <-> `@shared/components` cycle.
import {
    ConfirmationDialogService,
    ConfirmationResultWithOptions,
} from '../../components/cofirm-dialog/confimation-dialog.service';

/** Asks how to export items that can carry knowledge collections (flows, agents), in the app's confirmation dialog. */
@Injectable({
    providedIn: 'root',
})
export class ExportOptionsDialogService {
    private readonly confirmationDialog = inject(ConfirmationDialogService);

    /**
     * Emits the chosen options once the user confirms, and completes without a value when they cancel or close.
     * The knowledge box starts checked every time: a large archive stays a choice made for this export.
     */
    ask(count: number, labels: ExportEntityLabels): Observable<ExportOptions> {
        return this.confirmationDialog
            .confirmWithOptions({
                title: `Export ${pluralize(count, labels.singular, labels.plural)}`,
                message: `Knowledge data adds the knowledge collections the ${escapeHtml(labels.plural)} use, with their files, so they work after import. The archive can get large.`,
                checkbox: { label: 'Include knowledge data', checked: true },
                confirmText: 'Export',
                cancelText: 'Cancel',
                type: 'info',
            })
            .pipe(
                filter((result): result is ConfirmationResultWithOptions => result !== 'close' && result.confirmed),
                map((result) => ({ includeKnowledge: result.checked }))
            );
    }
}
