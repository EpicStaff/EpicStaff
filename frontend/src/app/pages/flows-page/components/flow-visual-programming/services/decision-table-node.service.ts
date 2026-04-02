import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateDecisionTableNodeRequest, GetDecisionTableNodeRequest } from '../models/decision-table-node.model';

export interface PaginatedDecisionTableResponse {
    count: number;
    next: string | null;
    previous: string | null;
    results: GetDecisionTableNodeRequest[];
}

@Injectable({
    providedIn: 'root',
})
export class DecisionTableNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'decision-table-node/';
    }

    createDecisionTableNode(request: CreateDecisionTableNodeRequest): Observable<GetDecisionTableNodeRequest> {
        return this.http.post<GetDecisionTableNodeRequest>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateDecisionTableNode(
        id: number,
        request: CreateDecisionTableNodeRequest
    ): Observable<GetDecisionTableNodeRequest> {
        return this.http.put<GetDecisionTableNodeRequest>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    getDecisionTableNodeById(id: number): Observable<GetDecisionTableNodeRequest> {
        return this.http.get<GetDecisionTableNodeRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    deleteDecisionTableNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
