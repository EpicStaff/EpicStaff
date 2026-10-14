import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../services/config/config.service';
import { CdtExplanationsSaveRequest, CdtExplanationsSaveResponse } from '../core/models/cdt-explain-api.model';

/**
 * Persists a Classification Decision Table node's generated explanations, and
 * nothing else on it.
 *
 * Kept apart from bulk save on purpose: bulk save sends the node as the canvas
 * holds it, unsaved grid edits included, and an explanation must never be the
 * reason those reach the server. Only the flow page injects this, through its
 * save queue — see `FlowVisualProgrammingComponent`.
 */
@Injectable({ providedIn: 'root' })
export class CdtExplanationsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    /** `nodeId` is the Django pk (`backendId`). */
    public saveExplanations(
        nodeId: number,
        request: CdtExplanationsSaveRequest
    ): Observable<CdtExplanationsSaveResponse> {
        return this.http.put<CdtExplanationsSaveResponse>(
            `${this.configService.apiUrl}classification-decision-table-node/${nodeId}/explanations/`,
            request
        );
    }
}
