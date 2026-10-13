import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, Observable, of, timeout } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import {
    IndexingEstimate,
    StartIndexingDtoRequest,
    StartIndexingDtoResponse,
    StopIndexingDtoRequest,
} from '../models/base-rag.model';

const ESTIMATE_TIMEOUT_MS = 3000;

@Injectable({ providedIn: 'root' })
export class RagIndexingService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    startIndexing(dto: StartIndexingDtoRequest): Observable<StartIndexingDtoResponse> {
        return this.http.post<StartIndexingDtoResponse>(`${this.configService.apiUrl}process-rag-indexing/`, dto);
    }

    estimateIndexing(dto: StartIndexingDtoRequest): Observable<IndexingEstimate> {
        return this.http.post<IndexingEstimate>(`${this.configService.apiUrl}process-rag-indexing/estimate/`, dto, {
            context: new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true),
        });
    }

    /**
     * Informational only: a failed or slow estimate resolves to null so it can never block indexing.
     */
    estimateIndexingOrNull(dto: StartIndexingDtoRequest): Observable<IndexingEstimate | null> {
        return this.estimateIndexing(dto).pipe(
            timeout(ESTIMATE_TIMEOUT_MS),
            catchError(() => of(null))
        );
    }

    stopIndexing(dto: StopIndexingDtoRequest): Observable<void> {
        return this.http.delete<void>(
            `${this.configService.apiUrl}process-rag-indexing/${dto.rag_type}/${dto.rag_id}/cancel/`
        );
    }
}
