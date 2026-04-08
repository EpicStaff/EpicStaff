import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';
import {
    CreateCollectionDtoRequest,
    CreateCollectionDtoResponse,
    DeleteCollectionResponse,
    GetCollectionDocumentsResponse,
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../models/collection.model';

@Injectable({
    providedIn: 'root',
})
export class CollectionsApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return `${this.configService.apiUrl}source-collections/`;
    }

    createCollection(): Observable<CreateCollectionDtoResponse> {
        const data: CreateCollectionDtoRequest = { collection_name: '' };

        return this.http.post<CreateCollectionDtoResponse>(this.apiUrl, data, {
            headers: this.httpHeaders,
        });
    }

    getCollections(): Observable<GetCollectionRequest[]> {
        return this.http.get<GetCollectionRequest[]>(this.apiUrl);
    }

    getCollectionById(id: number): Observable<CreateCollectionDtoResponse> {
        return this.http.get<CreateCollectionDtoResponse>(`${this.apiUrl}${id}/`);
    }

    getRagsByCollectionId(id: number): Observable<GetCollectionRagsResponse[]> {
        return this.http.get<GetCollectionRagsResponse[]>(`${this.apiUrl}${id}/available-rags/`);
    }

    getDocumentsByCollectionId(id: number): Observable<GetCollectionDocumentsResponse> {
        return this.http.get<GetCollectionDocumentsResponse>(`${this.apiUrl}${id}/documents/`);
    }

    updateCollectionById(
        id: number,
        body: Partial<CreateCollectionDtoResponse>
    ): Observable<CreateCollectionDtoResponse> {
        return this.http.patch<CreateCollectionDtoResponse>(`${this.apiUrl}${id}/`, body);
    }

    deleteCollectionById(id: number): Observable<DeleteCollectionResponse> {
        return this.http.delete<DeleteCollectionResponse>(`${this.apiUrl}${id}/`);
    }
}
