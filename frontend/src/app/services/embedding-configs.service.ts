import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../shared/models/api-request.model';
import {
  CreateEmbeddingConfigRequest,
  EmbeddingConfig,
  GetEmbeddingConfigRequest,
} from '../shared/models/embedding-config.model';
import { ConfigService } from './config/config.service';
import { Memory } from '../pages/running-graph/components/memory-sidebar/models/memory.model';

@Injectable({
  providedIn: 'root',
})
export class EmbeddingConfigsService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'embedding-configs/';
  }

  // GET all embedding configs with limit=1000
  getEmbeddingConfigs(): Observable<EmbeddingConfig[]> {
    const url = `${this.apiUrl}?limit=1000`;
    return this.http
      .get<ApiGetRequest<EmbeddingConfig>>(url)
      .pipe(map((response) => response.results));
  }
  getEmbeddingConfigsByProviderId(
    providerId: number
  ): Observable<EmbeddingConfig[]> {
    const url = `${this.apiUrl}?limit=1000&model_provider_id=${providerId}`;
    return this.http
      .get<ApiGetRequest<EmbeddingConfig>>(url)
      .pipe(map((response) => response.results));
  }
  // GET embedding config by ID
  getEmbeddingConfigById(id: number): Observable<EmbeddingConfig> {
    return this.http.get<EmbeddingConfig>(`${this.apiUrl}${id}/`);
  }

  // POST create embedding config
  createEmbeddingConfig(
    config: CreateEmbeddingConfigRequest
  ): Observable<GetEmbeddingConfigRequest> {
    return this.http.post<GetEmbeddingConfigRequest>(this.apiUrl, config, {
      headers: this.headers,
    });
  }

  // PUT update embedding config
  updateEmbeddingConfig(config: EmbeddingConfig): Observable<EmbeddingConfig> {
    return this.http.put<EmbeddingConfig>(
      `${this.apiUrl}${config.id}/`,
      config,
      {
        headers: this.headers,
      }
    );
  }

  // DELETE embedding config
  deleteEmbeddingConfig(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }
}
