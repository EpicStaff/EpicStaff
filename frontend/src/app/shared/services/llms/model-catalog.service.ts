import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { CatalogModel, CatalogProvider, ModelKind, ModelSchemas } from '@shared/models';
import { Observable, shareReplay } from 'rxjs';

import { ConfigService } from '../../../services/config';

/**
 * The read-only model catalog behind the config form: providers per kind, models per provider, and the settings and
 * connection schemas of one model. Schemas are the same for every organization and change only with a deploy, so each
 * model's are fetched once per session. The model list also holds the organization's own custom models, which change
 * when a config saves a new one, so it is fetched every time.
 */
@Injectable({ providedIn: 'root' })
export class ModelCatalogService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    /** Keyed by kind, provider and model. A failed request is sent again by the next subscriber. */
    private readonly schemasCache = new Map<string, Observable<ModelSchemas>>();

    private get apiUrl(): string {
        return this.configService.apiUrl + 'ai-models/';
    }

    /** Providers a config of `kind` can use, recommended first. */
    providers(kind: ModelKind): Observable<CatalogProvider[]> {
        return this.http.get<CatalogProvider[]>(`${this.apiUrl}providers/`, { params: { kind } });
    }

    /**
     * Every model of `provider` and `kind` whose name contains `search`: the organization's custom models first, then
     * the catalog's, recommended first; models past their deprecation date are left out.
     */
    models(kind: ModelKind, provider: string, search: string): Observable<CatalogModel[]> {
        const params = new HttpParams({ fromObject: { kind, provider, search } });
        return this.http.get<CatalogModel[]>(`${this.apiUrl}models/`, { params });
    }

    /** The settings and connection schemas of `model`, and the settings a new config starts with. */
    schemas(kind: ModelKind, provider: string, model: string): Observable<ModelSchemas> {
        const key = JSON.stringify([kind, provider, model]);
        let schemas = this.schemasCache.get(key);
        if (!schemas) {
            schemas = this.http
                .get<ModelSchemas>(`${this.apiUrl}schemas/`, { params: { kind, provider, model } })
                .pipe(shareReplay({ bufferSize: 1, refCount: false }));
            this.schemasCache.set(key, schemas);
        }
        return schemas;
    }
}
