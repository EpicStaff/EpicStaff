import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    CreatePersistenceTableEntryRequest,
    CreatePersistenceTableRequest,
    PersistenceEntriesQuery,
    PersistenceEntryLookupResponse,
    PersistenceTable,
    PersistenceTableEntry,
    UpdatePersistenceTableEntryRequest,
    UpdatePersistenceTableRequest,
} from '../models/persistence-table.model';

@Injectable({ providedIn: 'root' })
export class PersistenceTablesApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get tablesUrl(): string {
        return `${this.configService.apiUrl}persistence-tables/`;
    }

    private get entriesUrl(): string {
        return `${this.configService.apiUrl}persistence-table-entries/`;
    }

    getTables(): Observable<PersistenceTable[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<PersistenceTable>>(this.tablesUrl, {
                params,
                context: withPermission<ApiGetRequest<PersistenceTable>>(ResourceCode.PersistentData, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    createTable(body: CreatePersistenceTableRequest): Observable<PersistenceTable> {
        return this.http.post<PersistenceTable>(this.tablesUrl, body);
    }

    updateTable(id: number, body: UpdatePersistenceTableRequest): Observable<PersistenceTable> {
        return this.http.patch<PersistenceTable>(`${this.tablesUrl}${id}/`, body);
    }

    deleteTable(id: number): Observable<void> {
        return this.http.delete<void>(`${this.tablesUrl}${id}/`);
    }

    getEntries(query: PersistenceEntriesQuery): Observable<ApiGetRequest<PersistenceTableEntry>> {
        let params = new HttpParams().set('table', query.table).set('limit', query.limit).set('offset', query.offset);
        if (query.search) {
            params = params.set('search', query.search);
        }
        return this.http.get<ApiGetRequest<PersistenceTableEntry>>(this.entriesUrl, { params });
    }

    createEntry(body: CreatePersistenceTableEntryRequest): Observable<PersistenceTableEntry> {
        return this.http.post<PersistenceTableEntry>(this.entriesUrl, body);
    }

    updateEntry(id: number, body: UpdatePersistenceTableEntryRequest): Observable<PersistenceTableEntry> {
        return this.http.patch<PersistenceTableEntry>(`${this.entriesUrl}${id}/`, body);
    }

    deleteEntry(id: number): Observable<void> {
        return this.http.delete<void>(`${this.entriesUrl}${id}/`);
    }

    lookupEntries(tableId: number, keys: string[]): Observable<PersistenceEntryLookupResponse> {
        return this.http.post<PersistenceEntryLookupResponse>(
            `${this.tablesUrl}${tableId}/entries/lookup/`,
            { keys },
            {
                context: withPermission<PersistenceEntryLookupResponse>(
                    ResourceCode.PersistentData,
                    ActionCode.Read,
                    {}
                ),
            }
        );
    }
}
