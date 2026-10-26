import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ImportFlowRequestOptions, ImportResult } from '../../../core/models/import-result.model';
import { ImportExportService } from '../../../core/services/import-export.service';
import { GraphDto, PartialImportResponse } from '../models/graph.model';
import { FlowUsePermissionRefusalService } from './flow-use-permission-refusal.service';
import { FlowsStorageService } from './flows-storage.service';

/**
 * Copies and imports flows. The backend refuses these for a user without Flows:Use when the flow has trigger
 * nodes; that refusal is explained to the user and the observable completes without emitting. Any other
 * error reaches the caller unchanged.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowCopyImportFacadeService {
    private readonly flowsStorage = inject(FlowsStorageService);
    private readonly importExport = inject(ImportExportService);
    private readonly usePermissionRefusal = inject(FlowUsePermissionRefusalService);

    copyFlow(sourceId: number, newName: string): Observable<GraphDto> {
        return this.flowsStorage.copyFlow(sourceId, newName).pipe(this.usePermissionRefusal.catchRefusal('copy'));
    }

    importFlow(file: File, settings: ImportFlowRequestOptions): Observable<ImportResult> {
        return this.importExport.importFlow(file, settings).pipe(this.usePermissionRefusal.catchRefusal('import'));
    }

    partialImport(graphId: number, file: File): Observable<PartialImportResponse> {
        return this.importExport
            .partialImport(graphId, file)
            .pipe(this.usePermissionRefusal.catchRefusal('partialImport'));
    }
}
