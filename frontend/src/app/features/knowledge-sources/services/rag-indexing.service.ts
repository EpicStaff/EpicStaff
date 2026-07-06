import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    StartIndexingDtoRequest,
    StartIndexingDtoResponse,
    StopIndexingDtoRequest,
    StopIndexingDtoResponse,
} from '../models/base-rag.model';

@Injectable({ providedIn: 'root' })
export class RagIndexingService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    startIndexing(dto: StartIndexingDtoRequest): Observable<StartIndexingDtoResponse> {
        return this.http.post<StartIndexingDtoResponse>(`${this.configService.apiUrl}process-rag-indexing/`, dto);
    }

    stopIndexing(dto: StopIndexingDtoRequest): Observable<StopIndexingDtoResponse> {
        return this.http.post<StopIndexingDtoResponse>(`${this.configService.apiUrl}process-rag-indexing/cancel/`, dto);
    }
}
