import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable, switchMap } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    CreateTranscriptionConfigRequest,
    EnhancedTranscriptionConfig,
    GetRealtimeTranscriptionModelRequest,
    GetTranscriptionConfigRequest,
} from '../models/transcription-config.model';
import { ApiGetResponse, RealtimeTranscriptionModelsService } from './transcription-models.service';

@Injectable({
    providedIn: 'root',
})
export class TranscriptionConfigsService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService,
        private realtimeTranscriptionModelsService: RealtimeTranscriptionModelsService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'realtime-transcription-model-configs/';
    }

    // GET all transcription configs with limit=1000
    getTranscriptionConfigs(): Observable<GetTranscriptionConfigRequest[]> {
        const url = `${this.apiUrl}?limit=1000`;
        return this.http
            .get<ApiGetRequest<GetTranscriptionConfigRequest>>(url)
            .pipe(map((response) => response.results));
    }

    // GET transcription config by ID
    getTranscriptionConfigById(id: number): Observable<GetTranscriptionConfigRequest> {
        return this.http.get<GetTranscriptionConfigRequest>(`${this.apiUrl}${id}/`);
    }
    getTranscriptionConfigsByProviderId(providerId: number): Observable<GetTranscriptionConfigRequest[]> {
        const url = `${this.apiUrl}?limit=1000&model_provider_id=${providerId}`;
        return this.http
            .get<ApiGetRequest<GetTranscriptionConfigRequest>>(url)
            .pipe(map((response) => response.results));
    }
    // POST create transcription config
    createTranscriptionConfig(config: CreateTranscriptionConfigRequest): Observable<GetTranscriptionConfigRequest> {
        return this.http.post<GetTranscriptionConfigRequest>(this.apiUrl, config, {
            headers: this.headers,
        });
    }

    // DELETE transcription config
    deleteTranscriptionConfig(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    getEnhancedTranscriptionConfigs(): Observable<EnhancedTranscriptionConfig[]> {
        const url = `${this.apiUrl}?limit=1000`;
        // First load the available realtime transcription models, then fetch configs
        // and enrich each config with model_name by matching ids.
        return this.realtimeTranscriptionModelsService.getAllModels().pipe(
            switchMap((modelsRes: ApiGetResponse<GetRealtimeTranscriptionModelRequest>) => {
                const models = modelsRes && modelsRes.results ? modelsRes.results : [];
                return this.http.get<ApiGetRequest<GetTranscriptionConfigRequest>>(url).pipe(
                    map((response) =>
                        response.results.map((config) => {
                            const model = models.find(
                                (m: GetRealtimeTranscriptionModelRequest) =>
                                    m.id === config.realtime_transcription_model
                            );
                            return {
                                ...config,
                                model_name: model ? model.name : 'Unknown model',
                            } as EnhancedTranscriptionConfig;
                        })
                    )
                );
            })
        );
    }
}
