import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { extractHttpErrorMessage, showExportExclusionWarning } from '@shared/utils';
import { Observable } from 'rxjs';

import { ImportFlowRequestOptions, ImportResult } from '../../../core/models/import-result.model';
import { ImportExportService } from '../../../core/services/import-export.service';
import { ToastService } from '../../../services/notifications';
import { GraphDto, PartialImportResponse } from '../models/graph.model';
import { FlowsStorageService } from './flows-storage.service';
import { UsePermissionRefusalService } from './use-permission-refusal.service';

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
    private readonly usePermissionRefusal = inject(UsePermissionRefusalService);
    private readonly toastService = inject(ToastService);

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

    public exportFlow(flow: { id: number; name: string }): void {
        this.importExport.exportFlow(flow.id.toString()).subscribe({
            next: ({ blob, excluded }) => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${flow.name}_export_${Date.now()}.json`;
                a.click();
                window.URL.revokeObjectURL(url);

                this.toastService.success(`Flow "${flow.name}" exported successfully`);

                showExportExclusionWarning(this.toastService, excluded);
            },
            error: (error: HttpErrorResponse) => {
                console.error('Export failed:', error);
                this.toastService.error(extractHttpErrorMessage(error, `Failed to export flow "${flow.name}"`));
            },
        });
    }
}
