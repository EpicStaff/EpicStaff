import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import {
    CopyDocumentsRequest,
    CopyDocumentsResponse,
    DeleteDocumentResponse,
    DocumentContentScope,
    DocumentDetail,
    DocumentText,
    ImportFromStorageRequest,
    ImportFromStorageResponse,
    UploadDocumentResponse,
} from '../models/document.model';

@Injectable({
    providedIn: 'root',
})
export class DocumentsApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

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

    importFromStorage(collectionId: number, storageFileIds: number[]): Observable<ImportFromStorageResponse> {
        const body: ImportFromStorageRequest = { storage_file_ids: storageFileIds };
        return this.http.post<ImportFromStorageResponse>(
            `${this.apiUrl}/source-collection/${collectionId}/from-storage/`,
            body
        );
    }

    downloadDocuments(ids: number[]): Observable<Blob> {
        const params = new HttpParams().set('document_ids', ids.join(','));
        return this.http.get(`${this.apiUrl}/download/`, {
            responseType: 'blob',
            params,
        });
    }

    previewDocumentBlob(id: number): Observable<Blob> {
        return this.http.get(`${this.apiUrl}/${id}/preview/`, {
            responseType: 'blob',
        });
    }

    /** The document's text for editing, with the hash of that same text. */
    getDocumentText(id: number): Observable<DocumentText> {
        return this.http.get<DocumentText>(`${this.apiUrl}/${id}/content/`);
    }

    /** Replace a text document's content; the text travels as a file, so the upload limit applies. */
    updateDocumentContent(
        id: number,
        fileName: string,
        text: string,
        scope: DocumentContentScope,
        contentHash: string
    ): Observable<DocumentDetail> {
        const formData = new FormData();
        formData.append('file', new Blob([text], { type: 'text/plain;charset=utf-8' }), fileName);
        formData.append('scope', scope);
        formData.append('content_hash', contentHash);
        return this.http.put<DocumentDetail>(`${this.apiUrl}/${id}/content/`, formData);
    }

    copyDocuments(dto: CopyDocumentsRequest): Observable<CopyDocumentsResponse> {
        return this.http.post<CopyDocumentsResponse>(`${this.apiUrl}/copy/`, dto);
    }

    deleteDocumentById(id: number): Observable<DeleteDocumentResponse> {
        return this.http.delete<DeleteDocumentResponse>(`${this.apiUrl}/${id}/`);
    }
}
