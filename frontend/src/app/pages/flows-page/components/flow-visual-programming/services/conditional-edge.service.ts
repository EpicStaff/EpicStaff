import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateConditionalEdgeRequest, GetConditionalEdgeRequest } from '../models/conditional-edge.model';

@Injectable({
    providedIn: 'root',
})
export class ConditionalEdgeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'conditionaledges/';
    }

    createConditionalEdge(request: CreateConditionalEdgeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateConditionalEdge(id: number, request: CreateConditionalEdgeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    getConditionalEdgeById(id: number): Observable<GetConditionalEdgeRequest> {
        return this.http.get<GetConditionalEdgeRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    deleteConditionalEdge(id: number): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
