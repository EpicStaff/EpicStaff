import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { ExcludedExportEntity, ExportResult } from '@shared/models';
import { map, Observable } from 'rxjs';

import { PartialImportResponse } from '../../features/flows/models/graph.model';
import { ConfigService } from '../../services/config';
import { ImportFlowRequestOptions, ImportResult } from '../models/import-result.model';
import { InspectResult } from '../models/review-item.model';

export type { ImportFlowRequestOptions };

export type ExportFormat = 'json' | 'csv';

export interface PartialExportRequest {
    agent_node_list: number[];
    task_node_list: number[];
    python_node_list: number[];
    audio_transcription_node_list: number[];
    file_extractor_node_list: number[];
    subgraph_node_list: number[];
    webhook_trigger_node_list: number[];
    telegram_trigger_node_list: number[];
    decision_table_node_list: number[];
    classification_decision_table_node_list: number[];
    graph_note_list: number[];
    schedule_trigger_node_list: number[];
    edge_list: number[];
    knowledge_node_list: number[];
    key_value_node_list: number[];
}

interface ExportAllBody {
    graph_id?: number;
    status?: string[];
    is_error_cause?: boolean;
    id_search?: string;
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

    private get cdtApiUrl(): string {
        return this.configService.apiUrl + 'classification-decision-table-node/';
    }

    partialExport(graphId: number, body: PartialExportRequest): Observable<ExportResult> {
        return this.http
            .post(`${this.apiUrl}${graphId}/partial-export/`, body, {
                observe: 'response',
                responseType: 'blob',
            })
            .pipe(map((response) => this.toExportResult(response)));
    }

    partialImport(graphId: number, file: File): Observable<PartialImportResponse> {
        const formData = new FormData();
        formData.append('file', file);
        return this.http.post<PartialImportResponse>(`${this.apiUrl}${graphId}/partial-import/`, formData);
    }

    cdtExport(nodeId: number, format: ExportFormat): Observable<Blob> {
        return this.http.get(`${this.cdtApiUrl}${nodeId}/export/?export_format=${format}`, {
            responseType: 'blob',
        });
    }

    importFlow(file: File, settings: ImportFlowRequestOptions): Observable<ImportResult> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('preserve_uuids', String(settings.preserveUuids));
        formData.append('replace_existing', String(settings.replaceExisting));
        formData.append('import_labels', String(settings.importLabels));

        return this.http.post<ImportResult>(`${this.apiUrl}import/`, formData);
    }

    inspectFlow(file: File): Observable<InspectResult> {
        const formData = new FormData();
        formData.append('file', file);

        return this.http.post<InspectResult>(`${this.apiUrl}import/inspect/`, formData);
    }

    exportFlow(graphId: string): Observable<ExportResult> {
        return this.http
            .get(`${this.apiUrl}${graphId}/export/`, {
                observe: 'response',
                responseType: 'blob',
            })
            .pipe(map((response) => this.toExportResult(response)));
    }

    bulkExportFlow(ids: number[]): Observable<ExportResult> {
        return this.http
            .post(
                `${this.apiUrl}bulk-export/`,
                { ids },
                {
                    observe: 'response',
                    responseType: 'blob',
                }
            )
            .pipe(map((response) => this.toExportResult(response)));
    }

    // exportSession(id: number, format: ExportFormat): Observable<Blob> {
    //     return this.http.get(`${this.sessionsApiUrl}${id}/export/?export_format=${format}`, {
    //         responseType: 'blob',
    //     });
    // }

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
            is_error_cause?: boolean;
            id_search?: string | null;
        },
        format: ExportFormat = 'json'
    ): Observable<Blob> {
        const body: ExportAllBody = {};
        if (filters.graph != null) body.graph_id = filters.graph;
        if (filters.status != null && filters.status.length > 0) body.status = filters.status;
        if (filters.is_error_cause === true) body.is_error_cause = true;
        if (filters.id_search) body.id_search = filters.id_search;
        return this.http.post<Blob>(`${this.sessionsApiUrl}export_all/?export_format=${format}`, body, {
            responseType: 'blob' as 'json',
        });
    }

    private toExportResult(response: HttpResponse<Blob>): ExportResult {
        return {
            blob: response.body ?? new Blob(),
            excluded: this.parseExcludedHeader(response.headers.get('X-Export-Excluded')),
        };
    }

    private parseExcludedHeader(header: string | null): ExcludedExportEntity[] {
        if (!header) {
            return [];
        }
        let parsed: unknown;
        try {
            parsed = JSON.parse(header);
        } catch {
            return [];
        }
        if (!Array.isArray(parsed)) {
            return [];
        }
        return parsed.every(isExcludedExportEntity) ? parsed : [];
    }
}

function isExcludedExportEntity(value: unknown): value is ExcludedExportEntity {
    if (typeof value !== 'object' || value === null) {
        return false;
    }
    const { type, count, names } = value as Record<string, unknown>;
    return (
        typeof type === 'string' &&
        typeof count === 'number' &&
        Array.isArray(names) &&
        names.every((name) => typeof name === 'string')
    );
}
