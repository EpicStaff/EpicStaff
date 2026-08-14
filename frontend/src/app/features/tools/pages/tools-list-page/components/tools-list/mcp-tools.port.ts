import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable } from 'rxjs';

import { McpToolDialogComponent } from '../../../../components/mcp-tool-dialog/mcp-tool-dialog.component';
import { GetMcpToolRequest } from '../../../../models/mcp-tool.model';
import { BulkDeleteToolsResponse, GetBulkToolUsageItem, GetToolUsage } from '../../../../models/tool-config.model';
import { McpToolsService } from '../../../../services/mcp-tools/mcp-tools.service';
import { ToolsEventsService } from '../../../../services/tools-events.service';
import { ToolFilterAdapter } from '../../../../utils/tools-cards.util';
import { ToolKind } from '../tool-card/tool-card.model';
import { ToolsListPort } from './tools-list-port';

@Injectable()
export class McpToolsPort implements ToolsListPort<GetMcpToolRequest> {
    private readonly service = inject(McpToolsService);
    private readonly events = inject(ToolsEventsService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly kind: ToolKind = 'mcp';
    public readonly entityLabel = 'MCP tool';
    public readonly entityLabelPlural = 'MCP tools';

    public readonly filterAdapter: ToolFilterAdapter<GetMcpToolRequest> = {
        idOf: (t) => t.id,
        nameOf: (t) => t.name,
        labelIdsOf: (t) => t.labels ?? [],
        favoriteOf: (t) => t.is_favorite,
        searchableTextOf: (t) => [t.name, t.tool_name, t.transport],
    };

    public readonly createdEvent$: Observable<GetMcpToolRequest> = this.events.mcpToolCreated$;

    public isBuiltIn(_t: GetMcpToolRequest): boolean {
        void _t;
        return false;
    }
    public descriptionOf(t: GetMcpToolRequest): string {
        return `${t.tool_name} · ${t.transport}${t.timeout ? ` · ${t.timeout}s` : ''}`;
    }
    public exportFileName(toolName: string): string {
        return `${toolName}.json`;
    }
    public bulkExportFileName(): string {
        return `mcp-tools-export-${Date.now()}.json`;
    }

    public getAll(): Observable<GetMcpToolRequest[]> {
        return this.service.getMcpTools();
    }
    public copy(id: number, body: { name: string }): Observable<GetMcpToolRequest> {
        return this.service.copyMcpTool(id, body);
    }
    public exportOne(id: number): Observable<Blob> {
        return this.service.exportMcpTool(id);
    }
    public bulkExport(ids: number[]): Observable<Blob> {
        return this.service.bulkExportMcpTool(ids);
    }
    public patchLabels(id: number, labelIds: number[]): Observable<GetMcpToolRequest> {
        return this.service.patchMcpTool(id, { labels: labelIds });
    }
    public delete(id: number): Observable<void> {
        return this.service.deleteMcpTool(id);
    }
    public bulkDelete(ids: number[]): Observable<BulkDeleteToolsResponse> {
        return this.service.bulkDeleteMcpTool(ids);
    }
    public addFav(id: number): Observable<void> {
        return this.service.addToFavoritesMcpTool(id);
    }
    public delFav(id: number): Observable<void> {
        return this.service.deleteFromFavoritesMcpTool(id);
    }
    public importFile(file: File): Observable<unknown> {
        return this.service.importMcpTool(file);
    }
    public getBulkUsage(ids: number[]): Observable<GetBulkToolUsageItem[]> {
        return this.service.getBulkUsageDetailById(ids);
    }
    public getUsageDetail(id: number): Observable<GetToolUsage> {
        return this.service.getUsageDetailById(id);
    }

    public openConfigureDialog(dialog: Dialog, tool: GetMcpToolRequest): DialogRef<GetMcpToolRequest> {
        return dialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: { selectedTool: tool },
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });
    }

    public openCreateDialog(dialog: Dialog): void {
        const ref = dialog.open<GetMcpToolRequest>(McpToolDialogComponent, {
            data: {},
            maxWidth: '95vw',
            maxHeight: '90vh',
            autoFocus: true,
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) this.events.emitMcpToolCreated(result);
        });
    }
}
