import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import {
  GetMcpToolRequest,
  CreateMcpToolRequest,
  UpdateMcpToolRequest,
} from '../../models/mcp-tool.model';
import { ApiGetRequest } from '../../../../shared/models/api-request.model';
import { ConfigService } from '../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class McpToolsService {
  private http = inject(HttpClient);
  private configService = inject(ConfigService);

  private readonly httpHeaders = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  private get apiUrl(): string {
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
      .get<ApiGetRequest<GetMcpToolRequest>>(this.apiUrl, { params: httpParams })
      .pipe(map((response) => response.results));
  }

  getMcpToolById(id: number): Observable<GetMcpToolRequest> {
    return this.http.get<GetMcpToolRequest>(`${this.apiUrl}${id}/`, {
      headers: this.httpHeaders,
    });
  }

  createMcpTool(tool: CreateMcpToolRequest): Observable<GetMcpToolRequest> {
    return this.http.post<GetMcpToolRequest>(this.apiUrl, tool, {
      headers: this.httpHeaders,
    });
  }

  updateMcpTool(id: number, tool: CreateMcpToolRequest): Observable<GetMcpToolRequest> {
    return this.http.put<GetMcpToolRequest>(`${this.apiUrl}${id}/`, tool, {
      headers: this.httpHeaders,
    });
  }

  patchMcpTool(id: number, updates: UpdateMcpToolRequest): Observable<GetMcpToolRequest> {
    return this.http.patch<GetMcpToolRequest>(`${this.apiUrl}${id}/`, updates, {
      headers: this.httpHeaders,
    });
  }

  deleteMcpTool(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${id}/`, {
      headers: this.httpHeaders,
    });
  }
}

