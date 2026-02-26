import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map, shareReplay, switchMap } from 'rxjs/operators';
import { ApiGetRequest } from '../shared/models/api-request.model';
import { GetLlmModelRequest, LLM_Model } from '../shared/models';
import { ConfigService } from './config/config.service';

@Injectable({
  providedIn: 'root',
})
export class LLM_Models_Service {
  // Private property to hold the cached observable
  private models$!: Observable<GetLlmModelRequest[]>;

  constructor(private http: HttpClient, private configService: ConfigService) {
    this.initializeModelsCache();
  }

  private get apiUrl(): string {
    return this.configService.apiUrl + 'llm-models/';
  }

  private initializeModelsCache(): void {
    this.models$ = this.http
      .get<ApiGetRequest<GetLlmModelRequest>>(this.apiUrl)
      .pipe(
        map((response: ApiGetRequest<GetLlmModelRequest>) => response.results),
        shareReplay(1)
      );
  }

  getLLMModels(): Observable<GetLlmModelRequest[]> {
    return this.models$;
  }

  refreshModels(): Observable<GetLlmModelRequest[]> {
    // Re-create the cache
    this.initializeModelsCache();
    return this.models$;
  }

  getLLMModelById(id: number): Observable<LLM_Model> {
    return this.models$.pipe(
      switchMap((models) => {
        // Try to find the model in the cache first
        const cachedModel = models.find((model) => model.id === id);

        if (cachedModel) {
          return of(cachedModel as unknown as LLM_Model);
        }

        // If not found in cache, fetch from API
        return this.http.get<LLM_Model>(`${this.apiUrl}${id}/`);
      })
    );
  }
}
