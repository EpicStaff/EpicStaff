import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { RECYCLE_BIN_SOURCE_PATHS } from '../constants/recycle-bin-sources.constants';
import {
    GetRecycleBinContentsResponse,
    GetRecycleBinEntryResponse,
    GetStorageRecycleBinPageResponse,
    RecycleBinBulkPurgeResponse,
    RecycleBinBulkRestoreResponse,
    RecycleBinResourceSourceKey,
    RecycleBinSelection,
    RecycleBinSourceKey,
    RecycleBinStorageQuery,
} from '../models/recycle-bin.model';

/**
 * Recycle-bin endpoints. No `withPermission` context: the tab is only shown with READ and the
 * buttons only with CREATE / DELETE, so a 403 means permissions changed meanwhile and should surface.
 *
 * Every action, a single row's included, goes through the bulk endpoints
 * (`<list>/recycle-bin/restore|purge/` with `{ids}` or `{all: true}`), so they share one result shape.
 */
@Injectable({ providedIn: 'root' })
export class RecycleBinApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getEntries(source: RecycleBinResourceSourceKey): Observable<GetRecycleBinEntryResponse[]> {
        return this.http.get<GetRecycleBinEntryResponse[]>(this.binUrl(source));
    }

    getStorageEntries(
        limit: number,
        offset: number,
        query: RecycleBinStorageQuery
    ): Observable<GetStorageRecycleBinPageResponse> {
        let params = new HttpParams().set('limit', limit).set('offset', offset).set('ordering', query.ordering);
        if (query.search) params = params.set('search', query.search);
        if (query.itemType) params = params.set('item_type', query.itemType);
        return this.http.get<GetStorageRecycleBinPageResponse>(this.binUrl('storage'), { params });
    }

    /** Every content of one binned item, past the list's 100. */
    getContents(source: RecycleBinSourceKey, id: number): Observable<GetRecycleBinContentsResponse> {
        const url =
            source === 'storage'
                ? `${this.binUrl('storage')}${id}/contents/`
                : `${this.configService.apiUrl}${RECYCLE_BIN_SOURCE_PATHS[source]}${id}/recycle-bin-contents/`;
        return this.http.get<GetRecycleBinContentsResponse>(url);
    }

    restore(source: RecycleBinSourceKey, selection: RecycleBinSelection): Observable<RecycleBinBulkRestoreResponse> {
        return this.http.post<RecycleBinBulkRestoreResponse>(`${this.binUrl(source)}restore/`, selection);
    }

    purge(source: RecycleBinSourceKey, selection: RecycleBinSelection): Observable<RecycleBinBulkPurgeResponse> {
        return this.http.post<RecycleBinBulkPurgeResponse>(`${this.binUrl(source)}purge/`, selection);
    }

    private binUrl(source: RecycleBinSourceKey): string {
        return `${this.configService.apiUrl}${RECYCLE_BIN_SOURCE_PATHS[source]}recycle-bin/`;
    }
}
