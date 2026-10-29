// src/app/services/config.service.ts
import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { catchError, firstValueFrom, of } from 'rxjs';

import { environment } from '../../../environments/environment';

export interface AppConfig {
    apiUrl: string;
    type: string;
    realtimeApiUrl?: string;
    auditorUrl?: string;
    isChatEnabled?: boolean;
    chatApiUrl?: string;
    isAuditTrailEnabled?: boolean;
    /** The plugin platform is on (`PLUGINS_ENABLED`); nothing plugin-related renders while it is off. */
    isPluginsEnabled?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ConfigService {
    /**
     * `null` until {@link loadConfig} has run. A signal, so an effect or `computed()` made before then picks the loaded
     * values up: the storages are created while the app initializer is still loading the config.
     */
    private readonly configSignal = signal<AppConfig | null>(null);
    private readonly http = inject(HttpClient);

    async loadConfig(): Promise<void> {
        if (!environment.production) {
            this.configSignal.set({
                type: 'fallback',
                apiUrl: environment.apiUrl,
                realtimeApiUrl: environment.realtimeApiUrl,
                auditorUrl: environment.auditorUrl,
                isChatEnabled: environment.isChatEnabled ?? false,
                chatApiUrl: environment.chatApiUrl,
                isAuditTrailEnabled: environment.isAuditTrailEnabled ?? false,
                isPluginsEnabled: environment.isPluginsEnabled ?? false,
            });
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
                            auditorUrl: environment.auditorUrl,
                            isChatEnabled: environment.isChatEnabled ?? false,
                            chatApiUrl: environment.chatApiUrl,
                            isAuditTrailEnabled: environment.isAuditTrailEnabled ?? false,
                            isPluginsEnabled: environment.isPluginsEnabled ?? false,
                        } as AppConfig);
                    })
                )
            );

            this.configSignal.set(config);
        } catch (error) {
            console.error('Error loading configuration:', error);
            this.configSignal.set({
                type: 'fallback',
                apiUrl: environment.apiUrl,
                realtimeApiUrl: environment.realtimeApiUrl,
                auditorUrl: environment.auditorUrl,
                isChatEnabled: false,
                isAuditTrailEnabled: false,
                isPluginsEnabled: false,
            });
        }
    }

    getConfig(): AppConfig | null {
        return this.configSignal();
    }

    get apiUrl(): string {
        const config = this.configSignal();
        if (!config) {
            console.warn('Config not loaded, using fallback API URL');
            return environment.apiUrl;
        }
        return config.apiUrl;
    }

    get realtimeApiUrl(): string {
        const realtimeApiUrl = this.configSignal()?.realtimeApiUrl;
        if (!realtimeApiUrl) {
            console.warn('Realtime API URL not available, using fallback');
            return environment.realtimeApiUrl || '';
        }
        return realtimeApiUrl;
    }

    get auditorUrl(): string {
        const auditorUrl = this.configSignal()?.auditorUrl;
        if (!auditorUrl) {
            console.warn('Auditor URL not available, using fallback');
            return environment.auditorUrl || '';
        }
        return auditorUrl;
    }

    get isAuditTrailEnabled(): boolean {
        return this.configSignal()?.isAuditTrailEnabled ?? false;
    }

    get isPluginsEnabled(): boolean {
        return this.configSignal()?.isPluginsEnabled === true;
    }

    get isChatEnabled(): boolean {
        return this.configSignal()?.isChatEnabled ?? false;
    }

    get chatApiUrl(): string {
        const chatApiUrl = this.configSignal()?.chatApiUrl;
        if (!chatApiUrl) {
            console.warn('Chat API URL not available, using fallback');
            return environment.chatApiUrl || '/chat/';
        }
        return chatApiUrl;
    }
}
