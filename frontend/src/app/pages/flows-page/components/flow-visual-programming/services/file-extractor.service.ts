import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateFileExtractorNodeRequest, GetFileExtractorNodeRequest } from '../models/file-extractor.model';

@Injectable({
    providedIn: 'root',
})
export class FileExtractorService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'file-extractor-nodes/';
    }

    createFileExtractorNode(request: CreateFileExtractorNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateFileExtractorNode(id: number, request: CreateFileExtractorNodeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    getFileExtractorNodeById(id: number): Observable<GetFileExtractorNodeRequest> {
        return this.http.get<GetFileExtractorNodeRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    deleteFileExtractorNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
