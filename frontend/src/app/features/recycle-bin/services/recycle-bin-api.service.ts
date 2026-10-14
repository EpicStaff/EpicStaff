import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { RECYCLE_BIN_SOURCES } from '../constants/recycle-bin-sources.constants';
import {
    GetRecycleBinContentsResponse,
    GetRecycleBinPageResponse,
    GetStorageRecycleBinEntryResponse,
    RecycleBinBulkPurgeResponse,
    RecycleBinBulkRestoreResponse,
    RecycleBinEmptyResponse,
    RecycleBinListQuery,
    RecycleBinResourceSourceKey,
    RecycleBinSelection,
    RecycleBinSourceKey,
} from '../models/recycle-bin.model';

/**
 * Recycle-bin endpoints. No `withPermission` context: the tab is only shown with READ and the
 * buttons only with CREATE / DELETE, so a 403 means permissions changed meanwhile and should surface.
 *
 * Every action, a single row's included, goes through the bulk endpoints
 * (`<list>/recycle-bin/restore|purge/` with `{ids}`), so they share one result shape. "Empty recycle
 * bin" is one request to `recycle-bin/empty/`.
 */
@Injectable({ providedIn: 'root' })
export class RecycleBinApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    /** One page of a resource bin (`query.itemType` is storage's own and isn't sent). */
    getEntries(
        source: RecycleBinResourceSourceKey,
        limit: number,
        offset: number,
        query: RecycleBinListQuery
    ): Observable<GetRecycleBinPageResponse> {
        return this.http.get<GetRecycleBinPageResponse>(this.binUrl(source), {
            params: listParams(limit, offset, query),
        });
    }

    /** One page of the storage bin, which also filters by `item_type`. */
    getStorageEntries(
        limit: number,
        offset: number,
        query: RecycleBinListQuery
    ): Observable<GetRecycleBinPageResponse<GetStorageRecycleBinEntryResponse>> {
        let params = listParams(limit, offset, query);
        if (query.itemType) params = params.set('item_type', query.itemType);
        return this.http.get<GetRecycleBinPageResponse<GetStorageRecycleBinEntryResponse>>(this.binUrl('storage'), {
            params,
        });
    }

    /** Every content of one binned item, past the list's 100. */
    getContents(source: RecycleBinSourceKey, id: number): Observable<GetRecycleBinContentsResponse> {
        const url =
            source === 'storage'
                ? `${this.binUrl('storage')}${id}/contents/`
                : `${this.configService.apiUrl}${RECYCLE_BIN_SOURCES[source].path}${id}/recycle-bin-contents/`;
        return this.http.get<GetRecycleBinContentsResponse>(url);
    }

    restore(source: RecycleBinSourceKey, selection: RecycleBinSelection): Observable<RecycleBinBulkRestoreResponse> {
        return this.http.post<RecycleBinBulkRestoreResponse>(`${this.binUrl(source)}restore/`, selection);
    }

    purge(source: RecycleBinSourceKey, selection: RecycleBinSelection): Observable<RecycleBinBulkPurgeResponse> {
        return this.http.post<RecycleBinBulkPurgeResponse>(`${this.binUrl(source)}purge/`, selection);
    }

    /** Empties the active organization's whole bin, every type; superadmin only (anyone else gets a 403). */
    emptyAll(): Observable<RecycleBinEmptyResponse> {
        return this.http.post<RecycleBinEmptyResponse>(`${this.configService.apiUrl}recycle-bin/empty/`, {});
    }

    private binUrl(source: RecycleBinSourceKey): string {
        return `${this.configService.apiUrl}${RECYCLE_BIN_SOURCES[source].path}recycle-bin/`;
    }
}

/** The paging, search, ordering and count filter every bin list takes; empty filters are left out. */
function listParams(limit: number, offset: number, query: RecycleBinListQuery): HttpParams {
    let params = new HttpParams().set('limit', limit).set('offset', offset).set('ordering', query.ordering);
    if (query.search) params = params.set('search', query.search);
    if (query.contents) params = params.set('contents', query.contents);
    return params;
}
