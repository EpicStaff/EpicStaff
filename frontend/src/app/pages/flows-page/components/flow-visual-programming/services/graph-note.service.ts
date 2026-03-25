import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateGraphNoteRequest, GraphNote } from '../models/graph-note.model';

@Injectable({
    providedIn: 'root',
})
export class GraphNoteService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'graph-notes/';
    }

    createGraphNote(request: CreateGraphNoteRequest): Observable<GraphNote> {
        return this.http.post<GraphNote>(this.apiUrl, request, { headers: this.headers });
    }

    updateGraphNote(id: number, request: CreateGraphNoteRequest): Observable<GraphNote> {
        return this.http.put<GraphNote>(`${this.apiUrl}${id}/`, request, { headers: this.headers });
    }

    deleteGraphNote(id: string): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}
