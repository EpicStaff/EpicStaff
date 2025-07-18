import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../../shared/models/api-request.model';
import { GetLlmModelRequest, LLM_Model } from '../../models/llms/LLM.model';
import { ConfigService } from '../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class LLM_Models_Service {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'llm-models/';
  }

  getLLMModels(): Observable<GetLlmModelRequest[]> {
    const params = new HttpParams().set('limit', '1000');

    return this.http
      .get<ApiGetRequest<GetLlmModelRequest>>(this.apiUrl, {
        headers: this.headers,
        params,
      })
      .pipe(
        map((response: ApiGetRequest<GetLlmModelRequest>) => response.results)
      );
  }

  getModelsByProviderId(providerId: number): Observable<LLM_Model[]> {
    const params = new HttpParams()
      .set('llm_provider', providerId.toString())
      .set('limit', '1000');

    return this.http
      .get<ApiGetRequest<LLM_Model>>(this.apiUrl, {
        headers: this.headers,
        params,
      })
      .pipe(map((response) => response.results));
  }

  getLLMModelById(id: number): Observable<LLM_Model> {
    return this.http.get<LLM_Model>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }
}
