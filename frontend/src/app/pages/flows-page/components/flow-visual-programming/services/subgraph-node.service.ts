import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
    SubGraphNode,
    CreateSubGraphNodeRequest,
    UpdateSubGraphNodeRequest,
} from '../models/subgraph-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
    providedIn: 'root',
})
export class SubGraphNodeService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'subgraph-nodes/';
    }

    getSubGraphNode(id: number): Observable<SubGraphNode> {
        return this.http.get<SubGraphNode>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    createSubGraphNode(
        request: CreateSubGraphNodeRequest
    ): Observable<SubGraphNode> {
        return this.http.post<SubGraphNode>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateSubGraphNode(
        id: number,
        request: UpdateSubGraphNodeRequest
    ): Observable<SubGraphNode> {
        return this.http.patch<SubGraphNode>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteSubGraphNode(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}

