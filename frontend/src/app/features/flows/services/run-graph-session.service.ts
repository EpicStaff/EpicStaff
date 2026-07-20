import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';

interface RunGraphResponse {
    session_id: number;
}

@Injectable({
    providedIn: 'root',
})
export class RunGraphService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    runGraph(graphId: number, initialState?: Record<string, unknown>): Observable<RunGraphResponse> {
        const url = `${this.apiUrl}run-session/`;
        const formData = new FormData();
        formData.append('graph_id', graphId.toString());
        formData.append('initial_state', JSON.stringify(initialState || {}));

        return this.http.post<RunGraphResponse>(url, formData);
    }
}
