import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../../shared/models/api-request.model';
import { CreateEmbeddingModelRequest, EmbeddingModel } from '../../models/embeddings/embedding.model';
import { ConfigService } from '../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class EmbeddingModelsService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'embedding-models/';
  }

  getEmbeddingModels(providerId?: number, isVisible?: boolean): Observable<EmbeddingModel[]> {
    let params = new HttpParams().set('limit', '1000');

    if (providerId) {
      params = params.set('embedding_provider', providerId.toString());
    }

    if (isVisible !== undefined) {
      params = params.set('is_visible', isVisible.toString());
    }

    return this.http
      .get<ApiGetRequest<EmbeddingModel>>(this.apiUrl, {
        headers: this.headers,
        params,
      })
      .pipe(map((response: ApiGetRequest<EmbeddingModel>) => response.results));
  }

  getEmbeddingModelById(id: number): Observable<EmbeddingModel> {
    return this.http.get<EmbeddingModel>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }

  createModel(data: CreateEmbeddingModelRequest): Observable<EmbeddingModel> {
    return this.http.post<EmbeddingModel>(this.apiUrl, data, {
      headers: this.headers,
    });
  }

  patchModel(id: number, data: Partial<EmbeddingModel>): Observable<EmbeddingModel> {
    return this.http.patch<EmbeddingModel>(`${this.apiUrl}${id}/`, data, {
      headers: this.headers,
    });
  }

  deleteModel(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }
}
