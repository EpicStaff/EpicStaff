import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateCrewNodeRequest } from '../models/crew-node.model';

@Injectable({
    providedIn: 'root',
})
export class CrewNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'crewnodes/';
    }

    createCrewNode(request: CreateCrewNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateCrewNode(id: number, request: CreateCrewNodeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteCrewNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
