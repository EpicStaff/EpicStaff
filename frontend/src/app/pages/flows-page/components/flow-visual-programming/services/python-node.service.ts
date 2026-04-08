import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreatePythonNodeRequest } from '../models/python-node.model';

@Injectable({
    providedIn: 'root',
})
export class PythonNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'pythonnodes/';
    }

    createPythonNode(request: CreatePythonNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updatePythonNode(id: number, request: CreatePythonNodeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deletePythonNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
