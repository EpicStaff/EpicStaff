import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { forkJoin, map, Observable, of, switchMap } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { InspectResult } from '../../../../core/models/review-item.model';
import { ConfigService } from '../../../../services/config/config.service';
import {
    CreatePythonCodeToolPayload,
    CreatePythonCodeToolRequest,
    GetPythonCodeToolRequest,
    PatchPythonCodeToolRequest,
    UpdatePythonCodeToolRequest,
} from '../../models/python-code-tool.model';
import { BulkDeleteToolsResponse, GetBulkToolUsageItem, GetToolUsage } from '../../models/tool-config.model';

@Injectable({
    providedIn: 'root',
})
export class CustomToolsService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get baseUrl(): string {
        return `${this.configService.apiUrl}python-code-tool/`;
    }

    getPythonCodeTools(params?: { name?: string }): Observable<GetPythonCodeToolRequest[]> {
        // TODO: replace the auto-fetch-all behaviour with real pagination.
        const LIMIT = 50;
        const fetchSlice = (offset: number) => {
            let httpParams = new HttpParams().set('limit', String(LIMIT)).set('offset', String(offset));
            if (params?.name) httpParams = httpParams.set('name', params.name);
            return this.http.get<ApiGetRequest<GetPythonCodeToolRequest>>(this.baseUrl, { params: httpParams });
        };

        return fetchSlice(0).pipe(
            switchMap((first) => {
                if (first.results.length >= first.count) return of(first.results);
                const remainingOffsets: number[] = [];
                for (let offset = LIMIT; offset < first.count; offset += LIMIT) {
                    remainingOffsets.push(offset);
                }
                if (remainingOffsets.length === 0) return of(first.results);
                const rest$ = remainingOffsets.map((offset) => fetchSlice(offset).pipe(map((slice) => slice.results)));
                return forkJoin(rest$).pipe(map((slices) => [first.results, ...slices].flat()));
            })
        );
    }

    createPythonCodeTool(tool: CreatePythonCodeToolRequest): Observable<GetPythonCodeToolRequest> {
        return this.http.post<GetPythonCodeToolRequest>(this.baseUrl, tool, {
            headers: this.httpHeaders,
        });
    }

    /**
     * Create a Python code tool using the V2 payload shape (with `variables`
     * instead of the deprecated `args_schema`). Hits the same endpoint as
     * {@link createPythonCodeTool} - only the request body differs.
     */
    createPythonCodeToolV2(tool: CreatePythonCodeToolPayload): Observable<GetPythonCodeToolRequest> {
        return this.http.post<GetPythonCodeToolRequest>(this.baseUrl, tool, {
            headers: this.httpHeaders,
        });
    }

    copyPythonCodeTool(toolId: number): Observable<GetPythonCodeToolRequest> {
        return this.http.post<GetPythonCodeToolRequest>(
            `${this.baseUrl}${toolId}/copy/`,
            {},
            {
                headers: this.httpHeaders,
            }
        );
    }

    exportPythonCodeTool(toolId: number): Observable<Blob> {
        return this.http.get(`${this.baseUrl}${toolId}/export/`, { responseType: 'blob' });
    }

    updatePythonCodeTool(
        toolId: string,
        updatedTool: UpdatePythonCodeToolRequest
    ): Observable<GetPythonCodeToolRequest> {
        return this.http.put<GetPythonCodeToolRequest>(`${this.baseUrl}${toolId}/`, updatedTool, {
            headers: this.httpHeaders,
        });
    }

    addToFavoritesPythonCodeTool(id: number): Observable<void> {
        return this.http.post<void>(`${this.baseUrl}${id}/favorite/`, null, {
            headers: this.httpHeaders,
        });
    }

    deleteFromFavoritesPythonCodeTool(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/favorite/`, {
            headers: this.httpHeaders,
        });
    }

    updatePythonCodeToolV2(toolId: number, tool: CreatePythonCodeToolPayload): Observable<GetPythonCodeToolRequest> {
        return this.http.put<GetPythonCodeToolRequest>(`${this.baseUrl}${toolId}/`, tool, {
            headers: this.httpHeaders,
        });
    }

    patchPythonCodeTool(toolId: number, updates: PatchPythonCodeToolRequest): Observable<GetPythonCodeToolRequest> {
        return this.http.patch<GetPythonCodeToolRequest>(`${this.baseUrl}${toolId}/`, updates, {
            headers: this.httpHeaders,
        });
    }

    deletePythonCodeTool(toolId: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${toolId}/`, {
            headers: this.httpHeaders,
        });
    }

    bulkDeletePythonCodeTool(ids: number[]): Observable<BulkDeleteToolsResponse> {
        const body = { ids };
        return this.http.post<BulkDeleteToolsResponse>(`${this.baseUrl}bulk-delete/`, body, {
            headers: this.httpHeaders,
        });
    }

    bulkExportPythonCodeTool(ids: number[]): Observable<Blob> {
        const body = { ids };
        return this.http.post(`${this.baseUrl}bulk-export/`, body, {
            headers: this.httpHeaders,
            responseType: 'blob',
        });
    }

    importPythonCodeTool(file: File, importLabels = true): Observable<Record<string, unknown>> {
        const form = new FormData();
        form.append('file', file);
        form.append('import_labels', String(importLabels));
        return this.http.post<Record<string, unknown>>(`${this.baseUrl}import/`, form);
    }

    inspectPythonCodeTool(file: File): Observable<InspectResult> {
        const form = new FormData();
        form.append('file', file);
        return this.http.post<InspectResult>(`${this.baseUrl}import/inspect/`, form);
    }

    getPythonCodeToolById(id: number): Observable<GetPythonCodeToolRequest> {
        return this.http.get<GetPythonCodeToolRequest>(`${this.baseUrl}${id}/`, {
            headers: this.httpHeaders,
        });
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
