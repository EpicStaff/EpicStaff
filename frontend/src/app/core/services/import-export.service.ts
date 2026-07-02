import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../services/config/config.service';
import { ImportResult } from '../models/import-result.model';

export type ExportFormat = 'json' | 'csv';

export interface ImportFlowRequestOptions {
    preserveUuids: boolean;
    replaceExisting: boolean;
    importLabels: boolean;
}

interface ExportAllBody {
    graph_id?: number;
    status?: string[];
    node_name?: string;
    is_error_cause?: boolean;
}

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

    private get sessionsApiUrl(): string {
        return this.configService.apiUrl + 'sessions/';
    }

    importFlow(file: File, settings: ImportFlowRequestOptions): Observable<ImportResult> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('preserve_uuids', String(settings.preserveUuids));
        formData.append('replace_existing', String(settings.replaceExisting));
        formData.append('import_labels', String(settings.importLabels));

        return this.http.post<ImportResult>(`${this.apiUrl}import/`, formData);
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

    exportSession(id: number, format: ExportFormat): Observable<Blob> {
        return this.http.get(`${this.sessionsApiUrl}${id}/export/?export_format=${format}`, {
            responseType: 'blob',
        });
    }

    bulkExportSessions(ids: number[], format: ExportFormat): Observable<Blob> {
        return this.http.post(
            `${this.sessionsApiUrl}bulk-export/?export_format=${format}`,
            { ids },
            {
                responseType: 'blob',
            }
        );
    }

    exportAll(
        filters: {
            graph?: number | null;
            status?: string[] | null;
            node_name?: string | null;
            is_error_cause?: boolean;
        },
        format: ExportFormat = 'json'
    ): Observable<Blob> {
        const body: ExportAllBody = {};
        if (filters.graph != null) body.graph_id = filters.graph;
        if (filters.status != null && filters.status.length > 0) body.status = filters.status;
        if (filters.node_name != null) body.node_name = filters.node_name;
        if (filters.is_error_cause === true) body.is_error_cause = true;
        return this.http.post<Blob>(`${this.sessionsApiUrl}export_all/?export_format=${format}`, body, {
            responseType: 'blob' as 'json',
        });
    }
}
