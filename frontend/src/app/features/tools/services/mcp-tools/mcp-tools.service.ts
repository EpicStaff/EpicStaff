import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { forkJoin, Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../../core/http/permission-context';
import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { InspectResult } from '../../../../core/models/review-item.model';
import { ConfigService } from '../../../../services/config/config.service';
import { CreateMcpToolRequest, GetMcpToolRequest, UpdateMcpToolRequest } from '../../models/mcp-tool.model';
import { BulkDeleteToolsResponse, GetBulkToolUsageItem, GetToolUsage } from '../../models/tool-config.model';

@Injectable({
    providedIn: 'root',
})
export class McpToolsService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get baseUrl(): string {
        return `${this.configService.apiUrl}mcp-tools/`;
    }

    getMcpTools(params?: {
        name?: string;
        tool_name?: string;
        limit?: number;
        offset?: number;
    }): Observable<GetMcpToolRequest[]> {
        let httpParams = new HttpParams();

        if (params?.name) {
            httpParams = httpParams.set('name', params.name);
        }
        if (params?.tool_name) {
            httpParams = httpParams.set('tool_name', params.tool_name);
        }
        if (params?.limit) {
            httpParams = httpParams.set('limit', params.limit.toString());
        }
        if (params?.offset) {
            httpParams = httpParams.set('offset', params.offset.toString());
        }

        return this.http
            .get<ApiGetRequest<GetMcpToolRequest>>(this.baseUrl, {
                params: httpParams,
                context: withPermission<ApiGetRequest<GetMcpToolRequest>>(ResourceCode.Tools, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            }).pipe(map((response) => response.results));
    }

    getMcpToolById(id: number): Observable<GetMcpToolRequest> {
        return this.http.get<GetMcpToolRequest>(`${this.baseUrl}${id}/`, {
            headers: this.httpHeaders,
        });
    }

    createMcpTool(tool: CreateMcpToolRequest): Observable<GetMcpToolRequest> {
        return this.http.post<GetMcpToolRequest>(this.baseUrl, tool, {
            headers: this.httpHeaders,
        });
    }

    copyMcpTool(toolId: number, body: { name: string }): Observable<GetMcpToolRequest> {
        return this.http.post<GetMcpToolRequest>(`${this.baseUrl}${toolId}/copy/`, body, {
            headers: this.httpHeaders,
        });
    }

    exportMcpTool(toolId: number): Observable<Blob> {
        return this.http.get(`${this.baseUrl}${toolId}/export/`, { responseType: 'blob' });
    }

    updateMcpTool(id: number, tool: CreateMcpToolRequest): Observable<GetMcpToolRequest> {
        return this.http.put<GetMcpToolRequest>(`${this.baseUrl}${id}/`, tool, {
            headers: this.httpHeaders,
        });
    }

    addToFavoritesMcpTool(id: number): Observable<void> {
        return this.http.post<void>(`${this.baseUrl}${id}/favorite/`, null, {
            headers: this.httpHeaders,
        });
    }

    deleteFromFavoritesMcpTool(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/favorite/`, {
            headers: this.httpHeaders,
        });
    }

    patchMcpTool(id: number, updates: UpdateMcpToolRequest): Observable<GetMcpToolRequest> {
        return this.http.patch<GetMcpToolRequest>(`${this.baseUrl}${id}/`, updates, {
            headers: this.httpHeaders,
        });
    }

    deleteMcpTool(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`, {
            headers: this.httpHeaders,
        });
    }

    bulkDeleteMcpTool(ids: number[]): Observable<BulkDeleteToolsResponse> {
        const body = { ids };
        return this.http.post<BulkDeleteToolsResponse>(`${this.baseUrl}bulk-delete/`, body, {
            headers: this.httpHeaders,
        });
    }

    bulkExportMcpTool(ids: number[]): Observable<Blob> {
        const body = { ids };
        return this.http.post(`${this.baseUrl}bulk-export/`, body, {
            headers: this.httpHeaders,
            responseType: 'blob',
        });
    }

    importMcpTool(file: File, importLabels = true): Observable<Record<string, unknown>> {
        const form = new FormData();
        form.append('file', file);
        form.append('import_labels', String(importLabels));
        return this.http.post<Record<string, unknown>>(`${this.baseUrl}import/`, form);
    }

    inspectMcpTool(file: File): Observable<InspectResult> {
        const form = new FormData();
        form.append('file', file);
        return this.http.post<InspectResult>(`${this.baseUrl}import/inspect/`, form);
    }

    getUsageDetailById(toolId: number): Observable<GetToolUsage> {
        return this.http.get<GetToolUsage>(`${this.baseUrl}${toolId}/usage-detail/`, {
            headers: this.httpHeaders,
        });
    }

    getBulkUsageDetailById(toolIds: number[]): Observable<GetBulkToolUsageItem[]> {
        // Backend caps a single request at 50 ids, so split larger lists into
        // parallel chunks and merge the responses.
        const MAX_COUNT = 50;
        if (toolIds.length === 0) {
            return of([]);
        }
        if (toolIds.length <= MAX_COUNT) {
            return this.http.post<GetBulkToolUsageItem[]>(
                `${this.baseUrl}usage/`,
                { ids: toolIds },
                { headers: this.httpHeaders }
            );
        }

        const chunks: Observable<GetBulkToolUsageItem[]>[] = [];
        for (let i = 0; i < toolIds.length; i += MAX_COUNT) {
            const ids = toolIds.slice(i, i + MAX_COUNT);
            chunks.push(
                this.http.post<GetBulkToolUsageItem[]>(`${this.baseUrl}usage/`, { ids }, { headers: this.httpHeaders })
            );
        }
        return forkJoin(chunks).pipe(map((responses) => responses.flat()));
    }
}
