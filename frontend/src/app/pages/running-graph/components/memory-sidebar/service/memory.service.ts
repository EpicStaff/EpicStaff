import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiGetRequest } from '../../../../../core/models/api-request.model';
import { ConfigService } from '../../../../../services/config/config.service';
import { Memory } from '../models/memory.model';

@Injectable({
    providedIn: 'root',
})
export class MemoryService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl + 'memory/';
    }

    getMemories(): Observable<Memory[]> {
        return this.http
            .get<ApiGetRequest<Memory>>(this.apiUrl)
            .pipe(map((response: ApiGetRequest<Memory>) => response.results));
    }

    getMemoryById(id: string): Observable<Memory> {
        const url: string = `${this.apiUrl}${id}/`;
        return this.http.get<Memory>(url);
    }
    getMemoriesForSession(sessionId: string): Observable<Memory[]> {
        const url = `${this.apiUrl}?run_id=${sessionId}`;
        return this.http.get<ApiGetRequest<Memory>>(url).pipe(map((response) => response.results));
    }

    deleteMemory(id: string): Observable<unknown> {
        const url: string = `${this.apiUrl}${id}/`;
        return this.http.delete(url);
    }
}
