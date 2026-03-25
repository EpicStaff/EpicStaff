import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreateCodeAgentNodeRequest } from '../models/code-agent-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
    providedIn: 'root',
})
export class CodeAgentNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(private http: HttpClient, private configService: ConfigService) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'code-agent-nodes/';
    }

    createCodeAgentNode(request: CreateCodeAgentNodeRequest): Observable<any> {
        return this.http.post<any>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateCodeAgentNode(id: string, request: Partial<CreateCodeAgentNodeRequest>): Observable<any> {
        return this.http.patch<any>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteCodeAgentNode(id: string): Observable<any> {
        return this.http.delete(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
