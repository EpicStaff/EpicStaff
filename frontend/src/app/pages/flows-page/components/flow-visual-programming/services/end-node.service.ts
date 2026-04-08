import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateEndNodeRequest, EndNode, UpdateEndNodeRequest } from '../models/end-node.model';

@Injectable({
    providedIn: 'root',
})
export class EndNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'endnodes/';
    }

    getEndNode(id: number): Observable<EndNode> {
        return this.http.get<EndNode>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    partialUpdateEndNode(id: number, request: UpdateEndNodeRequest): Observable<EndNode> {
        return this.http.patch<EndNode>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    updateEndNode(id: number, request: CreateEndNodeRequest): Observable<EndNode> {
        return this.http.put<EndNode>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    createEndNode(request: CreateEndNodeRequest): Observable<EndNode> {
        return this.http.post<EndNode>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    deleteEndNode(id: number): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
