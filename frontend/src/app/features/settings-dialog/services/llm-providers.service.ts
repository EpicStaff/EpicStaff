import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../shared/models/api-request.model';
import { LLM_Provider, ModelTypes } from '../models/llm-provider.model';
import { ConfigService } from '../../../services/config/config.service';



@Injectable({
  providedIn: 'root',
})
export class LLM_Providers_Service {
  constructor(private http: HttpClient, private configService: ConfigService) { }

  private get apiUrl(): string {
    return this.configService.apiUrl + 'providers/';
  }

  getProviders(): Observable<LLM_Provider[]> {
    const params = new HttpParams().set('limit', '1000');

    return this.http
      .get<ApiGetRequest<LLM_Provider>>(this.apiUrl, { params })
      .pipe(map((response: ApiGetRequest<LLM_Provider>) => response.results));
  }

  getProvidersByQuery(type: ModelTypes): Observable<LLM_Provider[]> {
    let typeParam: string;

    switch (type) {
      case ModelTypes.EMBEDDING:
        typeParam = 'embedding';
        break;
      case ModelTypes.REALTIME:
        typeParam = 'realtime';
        break;
      case ModelTypes.LLM:
        typeParam = 'llm';
        break;
      case ModelTypes.TRANSCRIPTION:
        typeParam = 'transcription';
        break;
      default:
        typeParam = '';
    }

    const params = new HttpParams().set('limit', '1000').set('model_type', `${typeParam}`);

    return this.http
      .get<ApiGetRequest<LLM_Provider>>(this.apiUrl, { params })
      .pipe(map((response: ApiGetRequest<LLM_Provider>) => response.results));
  }
}