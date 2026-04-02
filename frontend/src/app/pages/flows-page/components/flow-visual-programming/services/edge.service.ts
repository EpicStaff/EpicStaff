import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateEdgeRequest } from '../models/edge.model';

@Injectable({
    providedIn: 'root',
})
export class EdgeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'edges/';
    }

    createEdge(request: CreateEdgeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateEdge(id: number, request: CreateEdgeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteEdge(id: number): Observable<unknown> {
        const url = `${this.apiUrl}${id}/`;
        return this.http.delete<unknown>(url, {
            headers: this.headers,
        });
    }
}
