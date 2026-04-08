import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateCodeAgentNodeRequest } from '../models/code-agent-node.model';

@Injectable({
    providedIn: 'root',
})
export class CodeAgentNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'code-agent-nodes/';
    }

    createCodeAgentNode(request: CreateCodeAgentNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateCodeAgentNode(id: string, request: Partial<CreateCodeAgentNodeRequest>): Observable<Record<string, unknown>> {
        return this.http.patch<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteCodeAgentNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
