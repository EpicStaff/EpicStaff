import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable } from 'rxjs';

import { CreateCustomToolDialogComponent } from '../../../../../../user-settings-page/tools/custom-tool-editor/create-custom-tool-dialog/create-custom-tool-dialog.component';
import { GetPythonCodeToolRequest } from '../../../../models/python-code-tool.model';
import { BulkDeleteToolsResponse, GetBulkToolUsageItem, GetToolUsage } from '../../../../models/tool-config.model';
import { CustomToolsService } from '../../../../services/custom-tools/custom-tools.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolFilterAdapter } from '../../../../utils/tools-cards.util';
import { ToolKind } from '../tool-card/tool-card.model';
import { ToolsListPort } from './tools-list-port';

@Injectable()
export class CustomToolsPort implements ToolsListPort<GetPythonCodeToolRequest> {
    private readonly service = inject(CustomToolsService);
    private readonly events = inject(ToolsEventsService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly kind: ToolKind = 'custom';
    public readonly entityLabel = 'custom tool';
    public readonly entityLabelPlural = 'custom tools';

    public readonly filterAdapter: ToolFilterAdapter<GetPythonCodeToolRequest> = {
        idOf: (t) => t.id,
        nameOf: (t) => t.name,
        labelIdsOf: (t) => t.labels ?? [],
        favoriteOf: (t) => t.is_favorite,
        searchableTextOf: (t) => [t.name, t.description],
    };

    public readonly createdEvent$: Observable<GetPythonCodeToolRequest> = this.events.customToolCreated$;

    public isBuiltIn(t: GetPythonCodeToolRequest): boolean {
        return t.built_in;
    }
    public descriptionOf(t: GetPythonCodeToolRequest): string {
        return t.description;
    }
    public exportFileName(toolName: string): string {
        return `${toolName}.json`;
    }
    public bulkExportFileName(): string {
        return `python-code-tools-export-${Date.now()}.json`;
    }

    public getAll(): Observable<GetPythonCodeToolRequest[]> {
        return this.service.getPythonCodeTools();
    }
    public copy(id: number, body: { name: string }): Observable<GetPythonCodeToolRequest> {
        return this.service.copyPythonCodeTool(id, body);
    }
    public exportOne(id: number): Observable<Blob> {
        return this.service.exportPythonCodeTool(id);
    }
    public bulkExport(ids: number[]): Observable<Blob> {
        return this.service.bulkExportPythonCodeTool(ids);
    }
    public patchLabels(id: number, labelIds: number[]): Observable<GetPythonCodeToolRequest> {
        return this.service.patchPythonCodeTool(id, { labels: labelIds });
    }
    public delete(id: number): Observable<void> {
        return this.service.deletePythonCodeTool(id);
    }
    public bulkDelete(ids: number[]): Observable<BulkDeleteToolsResponse> {
        return this.service.bulkDeletePythonCodeTool(ids);
    }
    public addFav(id: number): Observable<void> {
        return this.service.addToFavoritesPythonCodeTool(id);
    }
    public delFav(id: number): Observable<void> {
        return this.service.deleteFromFavoritesPythonCodeTool(id);
    }
    public importFile(file: File): Observable<unknown> {
        return this.service.importPythonCodeTool(file);
    }
    public getBulkUsage(ids: number[]): Observable<GetBulkToolUsageItem[]> {
        return this.service.getBulkUsageDetailById(ids);
    }
    public getUsageDetail(id: number): Observable<GetToolUsage> {
        return this.service.getUsageDetailById(id);
    }

    public openConfigureDialog(
        dialog: Dialog,
        tool: GetPythonCodeToolRequest,
        allTools: GetPythonCodeToolRequest[]
    ): DialogRef<GetPythonCodeToolRequest> {
        return dialog.open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent, {
            data: { pythonTools: allTools, selectedTool: tool },
        });
    }

    public openCreateDialog(dialog: Dialog): void {
        const ref = dialog.open<GetPythonCodeToolRequest>(CreateCustomToolDialogComponent);
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) this.events.emitCustomToolCreated(result);
        });
    }
}
