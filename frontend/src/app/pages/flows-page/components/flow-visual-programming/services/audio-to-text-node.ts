import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../../../services/config/config.service';
import { CreateAudioToTextNodeRequest, GetAudioToTextNodeRequest } from '../models/audio-to-text.model';

@Injectable({
    providedIn: 'root',
})
export class AudioToTextService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'audio-transcription-nodes/';
    }

    createAudioToTextNode(request: CreateAudioToTextNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrl, request, {
            headers: this.headers,
        });
    }

    updateAudioToTextNode(id: number, request: CreateAudioToTextNodeRequest): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrl}${id}/`, request, {
            headers: this.headers,
        });
    }

    getAudioToTextNodeById(id: number): Observable<GetAudioToTextNodeRequest> {
        return this.http.get<GetAudioToTextNodeRequest>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }

    deleteAudioToTextNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrl}${id}/`, {
            headers: this.headers,
        });
    }
}
