import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateStartNodeRequest, StartNode } from '../models/start-node.model';

export interface ApiGetRequest<T> {
    count: number;
    next: string | null;
    previous: string | null;
    results: T[];
}

@Injectable({
    providedIn: 'root',
})
export class StartNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'startnodes/';
    }

    createStartNode(request: CreateStartNodeRequest): Observable<StartNode> {
        return this.http.post<StartNode>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    getStartNodes(): Observable<StartNode[]> {
        return this.http
            .get<ApiGetRequest<StartNode>>(this.apiUrl, {
                headers: this.headers,
            })
            .pipe(map((response) => response.results));
    }

    getStartNode(id: number): Observable<StartNode> {
        return this.http.get<StartNode>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    partialUpdateStartNode(id: number, request: Partial<CreateStartNodeRequest>): Observable<StartNode> {
        return this.http.patch<StartNode>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    updateStartNode(id: number, request: CreateStartNodeRequest): Observable<StartNode> {
        return this.http.put<StartNode>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteStartNode(id: number): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
