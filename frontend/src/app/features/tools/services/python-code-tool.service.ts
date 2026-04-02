import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    CreatePythonCodeToolRequest,
    GetPythonCodeToolRequest,
    UpdatePythonCodeToolRequest,
} from '../models/python-code-tool.model';

@Injectable({
    providedIn: 'root',
})
export class PythonCodeToolService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get baseUrl(): string {
        return this.configService.apiUrl + 'python-code-tool/';
    }

    getPythonCodeTools(): Observable<GetPythonCodeToolRequest[]> {
        return this.http
            .get<ApiGetRequest<GetPythonCodeToolRequest>>(this.baseUrl)
            .pipe(map((response) => response.results));
    }

    createPythonCodeTool(tool: CreatePythonCodeToolRequest): Observable<CreatePythonCodeToolRequest> {
        return this.http.post<CreatePythonCodeToolRequest>(this.baseUrl, tool, {
            headers: this.headers,
        });
    }

    updatePythonCodeTool(
        toolId: string,
        updatedTool: UpdatePythonCodeToolRequest
    ): Observable<UpdatePythonCodeToolRequest> {
        return this.http.put<UpdatePythonCodeToolRequest>(`${this.baseUrl}${toolId}/`, updatedTool, {
            headers: this.headers,
        });
    }

    // DELETE method to remove a Python code tool
    deletePythonCodeTool(toolId: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${toolId}/`, {
            headers: this.headers,
        });
    }
}
