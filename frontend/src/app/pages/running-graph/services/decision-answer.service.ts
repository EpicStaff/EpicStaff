import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';

export interface DecisionAnswerRequest {
    decision_id: string;
    option_index: number | null;
    free_text: string | null;
}

@Injectable({
    providedIn: 'root',
})
export class DecisionAnswerService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'sessions/';
    }

    public submitDecisionAnswer(sessionId: string | number, data: DecisionAnswerRequest): Observable<unknown> {
        return this.http.post<unknown>(`${this.apiUrl}${sessionId}/decisions/answer/`, data);
    }
}
