import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { PartialImportResponse } from '../../features/flows/models/graph.model';
import { ConfigService } from '../../services/config';
import { ImportFlowRequestOptions, ImportResult } from '../models/import-result.model';
import { InspectResult } from '../models/review-item.model';
import { ExportFormat } from '../models/transfer-job.model';

export type { ImportFlowRequestOptions };

export type { ExportFormat };

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

@Injectable({
    providedIn: 'root',
})
export class ImportExportService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'graphs/';
    }

    partialImport(graphId: number, file: File): Observable<PartialImportResponse> {
        const formData = new FormData();
        formData.append('file', file);
        return this.http.post<PartialImportResponse>(`${this.apiUrl}${graphId}/partial-import/`, formData);
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
}
