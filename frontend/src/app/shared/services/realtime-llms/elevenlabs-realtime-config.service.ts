import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CreateElevenLabsRealtimeConfigRequest,
    ElevenLabsRealtimeConfig,
    UpdateElevenLabsRealtimeConfigRequest,
} from '../../models/realtime-voice/elevenlabs-realtime-config.model';

interface ApiListResponse<T> {
    results: T[];
}

@Injectable({ providedIn: 'root' })
export class ElevenLabsRealtimeConfigService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'elevenlabs-realtime-configs/';
    }

    getAll(): Observable<ElevenLabsRealtimeConfig[]> {
        return this.http
            .get<ApiListResponse<ElevenLabsRealtimeConfig>>(this.apiUrl, { headers: this.headers })
            .pipe(map((r) => r.results));
    }

    getById(id: number): Observable<ElevenLabsRealtimeConfig> {
        return this.http.get<ElevenLabsRealtimeConfig>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }

    create(data: CreateElevenLabsRealtimeConfigRequest): Observable<ElevenLabsRealtimeConfig> {
        return this.http.post<ElevenLabsRealtimeConfig>(this.apiUrl, data, { headers: this.headers });
    }

    update(data: UpdateElevenLabsRealtimeConfigRequest): Observable<ElevenLabsRealtimeConfig> {
        return this.http.put<ElevenLabsRealtimeConfig>(`${this.apiUrl}${data.id}/`, data, { headers: this.headers });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
