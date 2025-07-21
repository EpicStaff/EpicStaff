import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ToolConfig } from '../../features/tools/models/tool_config.model';

@Injectable({
  providedIn: 'root',
})
export class MockToolConfigService {
  private apiBaseUrl = 'http://127.0.0.1:8000/api/tool-configs/';

  constructor(private http: HttpClient) {}

  // Method to fetch all tool configurations
  getAllToolConfigs(): Observable<ToolConfig[]> {
    return this.http.get<ToolConfig[]>(this.apiBaseUrl);
  }

  // Method to fetch configurations for a specific tool
  getToolConfigByToolId(toolId: number): Observable<ToolConfig | null> {
    const url = `${this.apiBaseUrl}${toolId}`;

    return this.http.get<ToolConfig | null>(url);
  }

  // Method to update a tool configuration by ID
  updateToolConfigById(
    id: number,
    updatedConfig: Partial<ToolConfig>
  ): Observable<ToolConfig> {
    const url = `${this.apiBaseUrl}${id}/`;

    return this.http.put<ToolConfig>(url, updatedConfig);
  }

  // Method to create a new tool configuration
  createToolConfig(newConfig: ToolConfig): Observable<ToolConfig> {
    return this.http.post<ToolConfig>(this.apiBaseUrl, newConfig);
  }
}
