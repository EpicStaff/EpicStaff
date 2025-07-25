import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../../shared/models/api-request.model';
import { EmbeddingModel } from '../../models/embeddings/embedding.model';
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

  getEmbeddingModels(): Observable<EmbeddingModel[]> {
    return this.http
      .get<ApiGetRequest<EmbeddingModel>>(this.apiUrl, {
        headers: this.headers,
      })
      .pipe(map((response: ApiGetRequest<EmbeddingModel>) => response.results));
  }

  getEmbeddingModelById(id: number): Observable<EmbeddingModel> {
    return this.http.get<EmbeddingModel>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }
}
