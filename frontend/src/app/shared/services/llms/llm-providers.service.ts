import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { ActionCode, LLMProvider, ModelTypes, ResourceCode } from '@shared/models';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';

@Injectable({
    providedIn: 'root',
})
export class LLMProvidersService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'providers/';
    }

    getProviders(): Observable<LLMProvider[]> {
        const params = new HttpParams().set('limit', '1000');

        return this.http
            .get<ApiGetRequest<LLMProvider>>(this.apiUrl, {
                params,
                context: withPermission<ApiGetRequest<LLMProvider>>(ResourceCode.LlmConfigs, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response: ApiGetRequest<LLMProvider>) => response.results));
    }

    getProvidersByQuery(type: ModelTypes): Observable<LLMProvider[]> {
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
            .get<ApiGetRequest<LLMProvider>>(this.apiUrl, {
                params,
                context: withPermission<ApiGetRequest<LLMProvider>>(ResourceCode.LlmConfigs, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response: ApiGetRequest<LLMProvider>) => response.results));
    }
}
