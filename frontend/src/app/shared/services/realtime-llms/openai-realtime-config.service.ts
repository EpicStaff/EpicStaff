import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CreateOpenAIRealtimeConfigRequest,
    OpenAIRealtimeConfig,
    UpdateOpenAIRealtimeConfigRequest,
} from '../../models/realtime-voice/openai-realtime-config.model';

interface ApiListResponse<T> {
    results: T[];
}

@Injectable({ providedIn: 'root' })
export class OpenAIRealtimeConfigService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'openai-realtime-configs/';
    }

    getAll(): Observable<OpenAIRealtimeConfig[]> {
        return this.http
            .get<ApiListResponse<OpenAIRealtimeConfig>>(this.apiUrl, { headers: this.headers })
            .pipe(map((r) => r.results));
    }

    getById(id: number): Observable<OpenAIRealtimeConfig> {
        return this.http.get<OpenAIRealtimeConfig>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }

    create(data: CreateOpenAIRealtimeConfigRequest): Observable<OpenAIRealtimeConfig> {
        return this.http.post<OpenAIRealtimeConfig>(this.apiUrl, data, { headers: this.headers });
    }

    update(data: UpdateOpenAIRealtimeConfigRequest): Observable<OpenAIRealtimeConfig> {
        return this.http.put<OpenAIRealtimeConfig>(`${this.apiUrl}${data.id}/`, data, { headers: this.headers });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
