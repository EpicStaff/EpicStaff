import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { switchMap, tap } from 'rxjs/operators';

import { ImportFlowRequestOptions, ImportResult } from '../../../core/models/import-result.model';
import { ImportExportService } from '../../../core/services/import-export.service';
import { TransferExportService } from '../../../core/services/transfer-export.service';
import { StartedTransferJob, TransferJobsService } from '../../../core/services/transfer-jobs.service';
import { GraphDto, PartialImportResponse } from '../models/graph.model';
import { FlowExportOptionsDialogService } from './flow-export-options-dialog.service';
import { FlowsStorageService } from './flows-storage.service';
import { UsePermissionRefusalService } from './use-permission-refusal.service';

/**
 * Copies, imports and exports flows. The backend refuses a copy or an import for a user without Flows:Use when the
 * flow has trigger nodes; that refusal is explained to the user and the observable completes without emitting. Any
 * other error reaches the caller unchanged. An export first asks for its options, then runs as a background job.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowCopyImportFacadeService {
    private readonly flowsStorage = inject(FlowsStorageService);
    private readonly importExport = inject(ImportExportService);
    private readonly transferJobs = inject(TransferJobsService);
    private readonly transferExport = inject(TransferExportService);
    private readonly exportOptionsDialog = inject(FlowExportOptionsDialogService);
    private readonly usePermissionRefusal = inject(UsePermissionRefusalService);

    copyFlow(sourceId: number, newName: string): Observable<GraphDto> {
        return this.flowsStorage.copyFlow(sourceId, newName).pipe(this.usePermissionRefusal.catchRefusal('copy'));
    }

    importFlow(file: File, settings: ImportFlowRequestOptions): Observable<ImportResult> {
        return this.importExport.importFlow(file, settings).pipe(this.usePermissionRefusal.catchRefusal('import'));
    }

    /**
     * Uploads a `.zip` export archive and starts importing it as a background job; emits the job once the server
     * has accepted it. Follow it with TransferJobsService.waitForImport.
     */
    startFlowArchiveImport(file: File, settings: ImportFlowRequestOptions): Observable<StartedTransferJob> {
        return this.transferJobs
            .startImport('flows', file, settings)
            .pipe(this.usePermissionRefusal.catchRefusal('import'));
    }

    partialImport(graphId: number, file: File): Observable<PartialImportResponse> {
        return this.importExport
            .partialImport(graphId, file)
            .pipe(this.usePermissionRefusal.catchRefusal('partialImport'));
    }

    /**
     * Asks for the export options, then exports the flows as a background job. `onConfirmed` runs once the user
     * confirms the options, before the job starts; nothing runs when they cancel. Not tied to the caller: an export
     * the user started still downloads after they leave the page.
     */
    public exportFlows(ids: number[], onConfirmed?: () => void): void {
        this.exportOptionsDialog
            .ask(ids.length)
            .pipe(
                tap(() => onConfirmed?.()),
                switchMap((options) => this.transferExport.exportFlows(ids, options.includeKnowledge))
            )
            .subscribe();
    }
}
