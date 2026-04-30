import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { CreateRealtimeModel, RealtimeModel } from '@shared/models';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { ApiGetResponse } from '../transcription-llms/transcription-models.service';

@Injectable({
    providedIn: 'root',
})
export class RealtimeModelsService {
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'realtime-models/';
    }

    getAllModels(): Observable<RealtimeModel[]> {
        return this.http
            .get<ApiGetResponse<RealtimeModel>>(this.apiUrl, {
                headers: this.headers,
            })
            .pipe(map((response) => response.results));
    }

    getModelById(id: number): Observable<RealtimeModel> {
        return this.http.get<RealtimeModel>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    createModel(data: CreateRealtimeModel): Observable<RealtimeModel> {
        return this.http.post<RealtimeModel>(this.apiUrl, data, { headers: this.headers });
    }

    patchModel(id: number, data: Partial<CreateRealtimeModel>): Observable<RealtimeModel> {
        return this.http.patch<RealtimeModel>(`${this.apiUrl}${id}/`, data, { headers: this.headers });
    }
}
