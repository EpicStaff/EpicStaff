import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateLLMNodeRequest } from '../models/llm-node.model';

@Injectable({
    providedIn: 'root',
})
export class LLMNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'llmnodes/';
    }

    createLLMNode(request: CreateLLMNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, { headers: this.headers });
    }

    updateLLMNode(id: number, request: CreateLLMNodeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteLLMNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
