import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CreateGeminiRealtimeConfigRequest,
    GeminiRealtimeConfig,
    UpdateGeminiRealtimeConfigRequest,
} from '../../models/realtime-voice/gemini-realtime-config.model';

interface ApiListResponse<T> {
    results: T[];
}

@Injectable({ providedIn: 'root' })
export class GeminiRealtimeConfigService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'gemini-realtime-configs/';
    }

    getAll(): Observable<GeminiRealtimeConfig[]> {
        return this.http
            .get<ApiListResponse<GeminiRealtimeConfig>>(this.apiUrl, { headers: this.headers })
            .pipe(map((r) => r.results));
    }

    getById(id: number): Observable<GeminiRealtimeConfig> {
        return this.http.get<GeminiRealtimeConfig>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }

    create(data: CreateGeminiRealtimeConfigRequest): Observable<GeminiRealtimeConfig> {
        return this.http.post<GeminiRealtimeConfig>(this.apiUrl, data, { headers: this.headers });
    }

    update(data: UpdateGeminiRealtimeConfigRequest): Observable<GeminiRealtimeConfig> {
        return this.http.put<GeminiRealtimeConfig>(`${this.apiUrl}${data.id}/`, data, { headers: this.headers });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
