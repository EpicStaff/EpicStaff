// src/app/services/config.service.ts
import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, firstValueFrom, of } from 'rxjs';

import { environment } from '../../../environments/environment';

export interface AppConfig {
    apiUrl: string;
    type: string;
    realtimeApiUrl?: string;
    isEpicChatEnabled?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ConfigService {
    private config: AppConfig | null = null;
    private readonly http = inject(HttpClient);

    async loadConfig(): Promise<void> {
        if (!environment.production) {
            this.config = {
                type: 'fallback',
                apiUrl: environment.apiUrl,
                realtimeApiUrl: environment.realtimeApiUrl,
                isEpicChatEnabled: environment.isEpicChatEnabled ?? false,
            };
            return;
        }
        try {
            const config = await firstValueFrom(
                this.http.get<AppConfig>('/config.json').pipe(
                    catchError((error) => {
                        console.warn('Could not load config file:', error);

                        return of({
                            type: 'fallback',
                            apiUrl: environment.apiUrl,

                            realtimeApiUrl: environment.realtimeApiUrl,
                            isEpicChatEnabled: environment.isEpicChatEnabled ?? false,
                        } as AppConfig);
                    })
                )
            );

            this.config = config;
        } catch (error) {
            console.error('Error loading configuration:', error);
            this.config = {
                type: 'fallback',
                apiUrl: environment.apiUrl,
                realtimeApiUrl: environment.realtimeApiUrl,
                isEpicChatEnabled: false,
            };
        }
    }

    getConfig(): AppConfig | null {
        return this.config;
    }

    get apiUrl(): string {
        if (!this.config) {
            console.warn('Config not loaded, using fallback API URL');
            return environment.apiUrl;
        }
        return this.config.apiUrl;
    }

    get realtimeApiUrl(): string {
        if (!this.config || !this.config.realtimeApiUrl) {
            console.warn('Realtime API URL not available, using fallback');
            return environment.realtimeApiUrl || '';
        }
        return this.config.realtimeApiUrl;
    }

    get isEpicChatEnabled(): boolean {
        return this.config?.isEpicChatEnabled ?? false;
    }
}
