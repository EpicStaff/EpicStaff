import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../shared/models/api-request.model';
import { LLM_Provider } from '../models/LLM_provider.model';
import { ConfigService } from '../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class LLM_Providers_Service {
  constructor(private http: HttpClient, private configService: ConfigService) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'providers/';
  }

  getProviders(): Observable<LLM_Provider[]> {
    const params = new HttpParams().set('limit', '1000');

    return this.http
      .get<ApiGetRequest<LLM_Provider>>(this.apiUrl, { params })
      .pipe(map((response: ApiGetRequest<LLM_Provider>) => response.results));
  }
}
