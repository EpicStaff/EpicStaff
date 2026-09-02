import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../services/config/config.service';
import {
    CdtExplainRequest,
    CdtExplainResponse,
} from '../components/node-panels/classification-decision-table-node-panel/cdt-decision-tree-dialog/cdt-explain.model';

/**
 * Plain-language explanations of Classification Decision Table steps.
 *
 * The endpoint stores nothing and has no read side: each request carries the step
 * content from the open panel, so unsaved edits are explained as shown, and the
 * node id only scopes the request to the caller's organisation.
 *
 * Narrow on purpose — the decision-tree dialog is structurally unable to write to
 * the canvas, and injecting `HttpClient` there would give that guarantee away.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplainService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get apiUrl(): string {
        return `${this.configService.apiUrl}classification-decision-table-node/`;
    }

    /** `nodeId` is the Django pk (`backendId`); an unsaved node cannot be explained. */
    public explain(nodeId: number, request: CdtExplainRequest): Observable<CdtExplainResponse> {
        return this.http.post<CdtExplainResponse>(`${this.apiUrl}${nodeId}/explain/`, request);
    }
}
