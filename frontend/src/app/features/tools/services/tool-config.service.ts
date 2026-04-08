import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import { CreateToolConfigRequest, GetToolConfigRequest, ToolConfig } from '../models/tool-config.model';

@Injectable({
    providedIn: 'root',
})
export class ToolConfigService {
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'tool-configs/';
    }

    // GET all tool configs
    getToolConfigs(): Observable<GetToolConfigRequest[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<GetToolConfigRequest>>(this.apiUrl, {
                headers: this.headers,
                params,
            })
            .pipe(map((res) => res.results));
    }
    // POST create tool config
    createToolConfig(config: CreateToolConfigRequest): Observable<ToolConfig> {
        return this.http.post<ToolConfig>(this.apiUrl, config, {
            headers: this.headers,
        });
    }

    // PUT update tool config
    updateToolConfig(id: number, config: CreateToolConfigRequest): Observable<ToolConfig> {
        return this.http.put<ToolConfig>(`${this.apiUrl}${id}/`, config, {
            headers: this.headers,
        });
    }

    // DELETE delete tool config
    deleteToolConfig(id: number): Observable<unknown> {
        return this.http.delete(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
