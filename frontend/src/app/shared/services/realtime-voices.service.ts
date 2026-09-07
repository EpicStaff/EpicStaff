import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, shareReplay } from 'rxjs';

import { ConfigService } from '../../services/config';

export interface RealtimeVoice {
    id: string;
    name: string;
    description?: string;
}

export interface RealtimeVoicesMap {
    openai: RealtimeVoice[];
    gemini: RealtimeVoice[];
    [provider: string]: RealtimeVoice[];
}

@Injectable({ providedIn: 'root' })
export class RealtimeVoicesService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private voices$: Observable<RealtimeVoicesMap> | null = null;

    getVoices(): Observable<RealtimeVoicesMap> {
        if (!this.voices$) {
            this.voices$ = this.http
                .get<RealtimeVoicesMap>(this.configService.apiUrl + 'realtime-voices/')
                .pipe(shareReplay(1));
        }
        return this.voices$;
    }
}
