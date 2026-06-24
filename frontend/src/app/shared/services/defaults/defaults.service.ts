import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { AllDefaults, DefaultConfigBundle, DefaultEmbeddingConfig, DefaultLLMConfig } from '@shared/models';
import { forkJoin, Observable, of } from 'rxjs';
import { catchError, finalize, map, shareReplay, tap } from 'rxjs/operators';

import { ConfigService } from '../../../services/config/config.service';

const EMPTY_BUNDLE: DefaultConfigBundle = {
    default_agent_config: null,
    default_realtime_agent_config: null,
    default_crew_config: null,
    default_tool_config: null,
};

/**
 * Caches the org-wide "default" config rows so any consumer can grab them
 * without re-hitting the network. `load()` lazily fetches all three endpoints
 * in parallel on first call; subsequent calls reuse the cached result.
 */
@Injectable({
    providedIn: 'root',
})
export class DefaultsService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private dataSignal = signal<AllDefaults | null>(null);

    private inflight$?: Observable<AllDefaults>;

    public readonly data = this.dataSignal.asReadonly();
    public readonly loaded = computed(() => this.dataSignal() !== null);

    private get llmUrl(): string {
        return `${this.configService.apiUrl}default-llm-config/`;
    }
    private get embeddingUrl(): string {
        return `${this.configService.apiUrl}default-embedding-config/`;
    }
    private get bundleUrl(): string {
        return `${this.configService.apiUrl}default-config/`;
    }

    load(forceRefresh = false): Observable<AllDefaults> {
        if (this.loaded() && !forceRefresh) {
            return of(this.dataSignal()!);
        }
        if (this.inflight$ && !forceRefresh) {
            return this.inflight$;
        }

        this.inflight$ = forkJoin({
            defaultLlm: this.fetch<DefaultLLMConfig | null>(this.llmUrl, null),
            defaultEmbedding: this.fetch<DefaultEmbeddingConfig | null>(this.embeddingUrl, null),
            bundle: this.fetch<DefaultConfigBundle>(this.bundleUrl, EMPTY_BUNDLE),
        }).pipe(
            map(
                ({ defaultLlm, defaultEmbedding, bundle }): AllDefaults => ({
                    defaultLlm,
                    defaultEmbedding,
                    ...bundle,
                })
            ),
            tap((data) => this.dataSignal.set(data)),
            finalize(() => {
                this.inflight$ = undefined;
            }),
            shareReplay(1)
        );

        return this.inflight$;
    }

    private fetch<T>(url: string, fallback: T): Observable<T> {
        return this.http.get<T>(url).pipe(
            catchError((err: HttpErrorResponse) => {
                console.warn(`[DefaultsService] GET ${url} failed`, {
                    status: err.status,
                    statusText: err.statusText,
                });
                return of(fallback);
            })
        );
    }
}
