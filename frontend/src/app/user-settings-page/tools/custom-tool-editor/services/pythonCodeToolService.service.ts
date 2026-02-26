import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import {
  CreatePythonCodeToolRequest,
  GetPythonCodeToolRequest,
  UpdatePythonCodeToolRequest,
} from '../../../../features/tools/models/python-code-tool.model';
import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class PythonCodeToolService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get baseUrl(): string {
    return this.configService.apiUrl + 'python-code-tool/';
  }

  // GET method to retrieve the existing Python code tools
  getPythonCodeTools(): Observable<GetPythonCodeToolRequest[]> {
    return this.http
      .get<ApiGetRequest<GetPythonCodeToolRequest>>(this.baseUrl)
      .pipe(map((response) => response.results));
  }

  // POST method to create a new Python code tool
  createPythonCodeTool(
    tool: CreatePythonCodeToolRequest
  ): Observable<GetPythonCodeToolRequest> {
    return this.http.post<GetPythonCodeToolRequest>(this.baseUrl, tool, {
      headers: this.headers,
    });
  }

  // PUT method to update an existing Python code tool
  updatePythonCodeTool(
    toolId: string,
    updatedTool: UpdatePythonCodeToolRequest
  ): Observable<UpdatePythonCodeToolRequest> {
    return this.http.put<UpdatePythonCodeToolRequest>(
      `${this.baseUrl}${toolId}/`,
      updatedTool,
      { headers: this.headers }
    );
  }

  // DELETE method to remove a Python code tool
  deletePythonCodeTool(toolId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}${toolId}/`, {
      headers: this.headers,
    });
  }
}
