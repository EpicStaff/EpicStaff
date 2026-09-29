import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    CreateKeyValueTableEntryRequest,
    CreateKeyValueTableRequest,
    KeyValueEntriesQuery,
    KeyValueEntryLookupResponse,
    KeyValueTable,
    KeyValueTableEntry,
    KeyValueTableEntryListItem,
    UpdateKeyValueTableEntryRequest,
    UpdateKeyValueTableRequest,
} from '../models/key-value-table.model';

@Injectable({ providedIn: 'root' })
export class KeyValueTablesApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get tablesUrl(): string {
        return `${this.configService.apiUrl}key-value-tables/`;
    }

    private get entriesUrl(): string {
        return `${this.configService.apiUrl}key-value-table-entries/`;
    }

    getTables(): Observable<KeyValueTable[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<KeyValueTable>>(this.tablesUrl, {
                params,
                context: withPermission<ApiGetRequest<KeyValueTable>>(ResourceCode.KeyValueTables, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    createTable(body: CreateKeyValueTableRequest): Observable<KeyValueTable> {
        return this.http.post<KeyValueTable>(this.tablesUrl, body);
    }

    updateTable(id: number, body: UpdateKeyValueTableRequest): Observable<KeyValueTable> {
        return this.http.patch<KeyValueTable>(`${this.tablesUrl}${id}/`, body);
    }

    deleteTable(id: number): Observable<void> {
        return this.http.delete<void>(`${this.tablesUrl}${id}/`);
    }

    getEntries(query: KeyValueEntriesQuery): Observable<ApiGetRequest<KeyValueTableEntryListItem>> {
        let params = new HttpParams().set('table', query.table).set('limit', query.limit).set('offset', query.offset);
        if (query.search) {
            params = params.set('search', query.search);
        }
        if (query.ordering) {
            params = params.set('ordering', query.ordering);
        }
        return this.http.get<ApiGetRequest<KeyValueTableEntryListItem>>(this.entriesUrl, { params });
    }

    getEntry(id: number): Observable<KeyValueTableEntry> {
        return this.http.get<KeyValueTableEntry>(`${this.entriesUrl}${id}/`);
    }

    createEntry(body: CreateKeyValueTableEntryRequest): Observable<KeyValueTableEntry> {
        return this.http.post<KeyValueTableEntry>(this.entriesUrl, body);
    }

    updateEntry(id: number, body: UpdateKeyValueTableEntryRequest): Observable<KeyValueTableEntry> {
        return this.http.patch<KeyValueTableEntry>(`${this.entriesUrl}${id}/`, body);
    }

    deleteEntry(id: number): Observable<void> {
        return this.http.delete<void>(`${this.entriesUrl}${id}/`);
    }

    lookupEntries(tableId: number, keys: string[]): Observable<KeyValueEntryLookupResponse> {
        return this.http.post<KeyValueEntryLookupResponse>(
            `${this.tablesUrl}${tableId}/entries/lookup/`,
            { keys },
            {
                context: withPermission<KeyValueEntryLookupResponse>(ResourceCode.KeyValueTables, ActionCode.Read, {}),
            }
        );
    }
}
