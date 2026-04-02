import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../services/config/config.service';

@Injectable({
    providedIn: 'root',
})
export class ImportExportService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'graphs/';
    }

    importFlow(file: File, preserveUuids: boolean = false): Observable<Record<string, unknown>> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('preserve_uuids', String(preserveUuids));

        return this.http.post<Record<string, unknown>>(`${this.apiUrl}import/`, formData);
    }

    exportFlow(graphId: string): Observable<Blob> {
        return this.http.get(`${this.apiUrl}${graphId}/export/`, {
            responseType: 'blob',
        });
    }

    bulkExportFlow(ids: number[]): Observable<Blob> {
        return this.http.post(
            `${this.apiUrl}bulk-export/`,
            { ids },
            {
                responseType: 'blob',
            }
        );
    }
}
