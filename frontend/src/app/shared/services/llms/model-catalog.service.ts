import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { CatalogModel, CatalogProvider, ModelKind, ModelSchemas } from '@shared/models';
import { map, Observable, shareReplay } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

/**
 * The read-only model catalog behind the config form: providers per kind, models per provider, and the settings and
 * connection schemas of one model. The catalog is the same for every organization and changes only with a deploy, so
 * each model's schemas are fetched once per session.
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
     * The first page of `provider`'s models of `kind` whose name contains `search`, recommended first; models past
     * their deprecation date are left out.
     */
    models(kind: ModelKind, provider: string, search: string): Observable<CatalogModel[]> {
        const params = new HttpParams({ fromObject: { kind, provider, search } });
        return this.http
            .get<ApiGetRequest<CatalogModel>>(`${this.apiUrl}models/`, { params })
            .pipe(map((page) => page.results));
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
