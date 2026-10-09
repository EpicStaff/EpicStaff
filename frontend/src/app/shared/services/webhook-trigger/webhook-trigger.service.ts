import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { WebhookTriggerModel, WebhookTriggerPayload } from '@shared/models';
import { map, Observable, Subject, tap } from 'rxjs';

import { ConfigService } from '../../../services/config';

interface ApiListResponse<T> {
    results: T[];
}

@Injectable({ providedIn: 'root' })
export class WebhookTriggerService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    /** Emits whenever a trigger is created/updated/deleted, so lists can refresh. */
    readonly changed$ = new Subject<void>();

    private get apiUrl(): string {
        return this.configService.apiUrl + 'webhook-triggers/';
    }

    list(): Observable<WebhookTriggerModel[]> {
        return this.http
            .get<ApiListResponse<WebhookTriggerModel>>(this.apiUrl, { headers: this.headers })
            .pipe(map((r) => r.results));
    }

    getById(id: number): Observable<WebhookTriggerModel> {
        return this.http.get<WebhookTriggerModel>(`${this.apiUrl}${id}/`, { headers: this.headers });
    }

    create(trigger: WebhookTriggerModel): Observable<WebhookTriggerModel> {
        return this.http
            .post<WebhookTriggerModel>(this.apiUrl, this.toPayload(trigger), { headers: this.headers })
            .pipe(tap(() => this.changed$.next()));
    }

    update(id: number, trigger: WebhookTriggerModel): Observable<WebhookTriggerModel> {
        return this.http
            .patch<WebhookTriggerModel>(`${this.apiUrl}${id}/`, this.toPayload(trigger), { headers: this.headers })
            .pipe(tap(() => this.changed$.next()));
    }

    delete(id: number): Observable<void> {
        return this.http
            .delete<void>(`${this.apiUrl}${id}/`, { headers: this.headers })
            .pipe(tap(() => this.changed$.next()));
    }

    // Callers may pass a trigger loaded from the API (e.g. the edit dialog saved without changes),
    // so pick the writable fields instead of echoing read-only ones back. Absent auth keys stay
    // absent: the backend only touches the trigger's auth when one of them is sent.
    private toPayload(trigger: WebhookTriggerModel): WebhookTriggerPayload {
        const payload: WebhookTriggerPayload = {
            path: trigger.path,
            provider_type: trigger.provider_type,
            ngrok_config: trigger.ngrok_config,
            localhost_config: trigger.localhost_config,
        };
        if (trigger.auth_kind !== undefined) payload.auth_kind = trigger.auth_kind;
        if (trigger.auth_secret_id !== undefined) payload.auth_secret_id = trigger.auth_secret_id;
        return payload;
    }
}
