import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config/config.service';
import {
    CreatePythonCodeToolPayload,
    CreatePythonCodeToolRequest,
    GetPythonCodeToolRequest,
    PatchPythonCodeToolRequest,
    UpdatePythonCodeToolRequest,
} from '../../models/python-code-tool.model';
import { GetBulkToolUsageItem, GetToolUsage } from '../../models/tool-config.model';

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

    getPythonCodeTools(): Observable<GetPythonCodeToolRequest[]> {
        return this.http
            .get<ApiGetRequest<GetPythonCodeToolRequest>>(this.baseUrl)
            .pipe(map((response) => response.results));
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

    copyPythonCodeTool(toolId: number, body: { name?: string } = {}): Observable<GetPythonCodeToolRequest> {
        return this.http.post<GetPythonCodeToolRequest>(`${this.baseUrl}${toolId}/copy/`, body, {
            headers: this.httpHeaders,
        });
    }

    updatePythonCodeTool(
        toolId: string,
        updatedTool: UpdatePythonCodeToolRequest
    ): Observable<GetPythonCodeToolRequest> {
        return this.http.put<GetPythonCodeToolRequest>(`${this.baseUrl}${toolId}/`, updatedTool, {
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

    bulkDeletePythonCode(ids: number[]): Observable<void> {
        const body = { ids };
        return this.http.post<void>(`${this.baseUrl}bulk-delete/`, body, {
            headers: this.httpHeaders,
        });
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
        const body = { ids: toolIds };
        return this.http.post<GetBulkToolUsageItem[]>(`${this.baseUrl}usage/`, body, {
            headers: this.httpHeaders,
        });
    }
}
