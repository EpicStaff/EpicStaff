import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import {
  CreatePythonCodeToolRequest,
  GetPythonCodeToolRequest,
  UpdatePythonCodeToolRequest,
} from '../../models/python-code-tool.model';
import { ApiGetRequest } from '../../../../shared/models/api-request.model';
import { ConfigService } from '../../../../services/config/config.service';

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

  createPythonCodeTool(
    tool: CreatePythonCodeToolRequest
  ): Observable<GetPythonCodeToolRequest> {
    return this.http.post<GetPythonCodeToolRequest>(this.baseUrl, tool, {
      headers: this.httpHeaders,
    });
  }

  updatePythonCodeTool(
    toolId: string,
    updatedTool: UpdatePythonCodeToolRequest
  ): Observable<GetPythonCodeToolRequest> {
    return this.http.put<GetPythonCodeToolRequest>(
      `${this.baseUrl}${toolId}/`,
      updatedTool,
      { headers: this.httpHeaders }
    );
  }

  deletePythonCodeTool(toolId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}${toolId}/`, {
      headers: this.httpHeaders,
    });
  }

  getPythonCodeToolById(id: number): Observable<GetPythonCodeToolRequest> {
    return this.http.get<GetPythonCodeToolRequest>(`${this.baseUrl}${id}/`, {
      headers: this.httpHeaders,
    });
  }
}
