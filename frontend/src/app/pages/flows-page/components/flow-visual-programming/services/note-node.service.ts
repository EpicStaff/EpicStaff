import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreateNoteNodeRequest, NoteNode } from '../models/note-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
    providedIn: 'root',
})
export class NoteNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(private http: HttpClient, private configService: ConfigService) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'note-nodes/';
    }

    createNoteNode(request: CreateNoteNodeRequest): Observable<NoteNode> {
        return this.http.post<NoteNode>(this.apiUrl, request, { headers: this.headers });
    }

    updateNoteNode(id: number, request: CreateNoteNodeRequest): Observable<NoteNode> {
        return this.http.put<NoteNode>(`${this.apiUrl}${id}/`, request, { headers: this.headers });
    }

    deleteNoteNode(id: string): Observable<any> {
        return this.http.delete(`${this.apiUrl}${id}/`, { headers: this.headers });
    }
}

