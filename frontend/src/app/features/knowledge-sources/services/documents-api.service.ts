import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';
import { DeleteDocumentResponse, UploadDocumentResponse } from '../models/document.model';

@Injectable({
    providedIn: 'root',
})
export class DocumentsApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return `${this.configService.apiUrl}documents`;
    }

    uploadDocuments(collectionId: number, files: File[]): Observable<UploadDocumentResponse> {
        const formData = new FormData();

        files.forEach((file) => {
            formData.append('files', file);
        });

        return this.http.post<UploadDocumentResponse>(
            `${this.apiUrl}/source-collection/${collectionId}/upload/`,
            formData
        );
    }

    deleteDocumentById(id: number): Observable<DeleteDocumentResponse> {
        return this.http.delete<DeleteDocumentResponse>(`${this.apiUrl}/${id}/`);
    }
}
