import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogService, ConfirmationResultWithOptions } from '@shared/components';
import { pluralize } from '@shared/utils';
import { Observable } from 'rxjs';
import { filter, map } from 'rxjs/operators';

import { FlowExportOptions } from '../models/flow-export-options.model';

/** Asks how to export flows, in the app's confirmation dialog. */
@Injectable({
    providedIn: 'root',
})
export class FlowExportOptionsDialogService {
    private readonly confirmationDialog = inject(ConfirmationDialogService);

    /**
     * Emits the chosen options once the user confirms, and completes without a value when they cancel or close.
     * The knowledge box starts checked every time: a large archive stays a choice made for this export.
     */
    ask(flowCount: number): Observable<FlowExportOptions> {
        return this.confirmationDialog
            .confirmWithOptions({
                title: `Export ${pluralize(flowCount, 'flow', 'flows')}`,
                message:
                    'Knowledge data adds the knowledge collections the flows use, with their files, so they work after import. The archive can get large.',
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
