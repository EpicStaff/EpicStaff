import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';
import { ApiGetRequest } from '../../../shared/models/api-request.model';
import { Tool } from '../models/tool.model';
import { ConfigService } from '../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class ToolsService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  private tools$: Observable<Tool[]> | null = null;

  constructor(private http: HttpClient, private configService: ConfigService) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'tools/';
  }

  getTools(): Observable<Tool[]> {
    if (this.tools$) {
      return this.tools$;
    }

    const params = new HttpParams().set('limit', '1000');

    this.tools$ = this.http
      .get<ApiGetRequest<Tool>>(this.apiUrl, {
        headers: this.headers,
        params,
      })
      .pipe(
        map((response) => response.results),
        shareReplay({ bufferSize: 1, refCount: true })
      );

    return this.tools$;
  }

  getToolsByIds(toolIds: number[]): Observable<Tool[]> {
    const requests: Observable<Tool>[] = toolIds.map((id) =>
      this.http.get<Tool>(`${this.apiUrl}${id}/`)
    );
    return forkJoin(requests);
  }

  updateTool(tool: Tool): Observable<Tool> {
    return this.http.put<Tool>(`${this.apiUrl}${tool.id}/`, tool, {
      headers: this.headers,
    });
  }

  patchTool(toolId: number, updates: Partial<Tool>): Observable<Tool> {
    return this.http.patch<Tool>(`${this.apiUrl}${toolId}/`, updates, {
      headers: this.headers,
    });
  }

  /**
   * Clears the cached tools and forces a fresh fetch on next getTools() call
   */
  refreshTools(): void {
    this.tools$ = null;
  }
}
