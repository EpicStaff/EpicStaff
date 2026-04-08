import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ApiGetRequest } from '../../../../../core/models/api-request.model';
import { ConfigService } from '../../../../../services/config/config.service';
import { CreateWebhookTriggerNodeRequest, GetWebhookTriggerNodeRequest } from '../models/webhook-trigger';
export interface WebhookTrigger {
    id: number;
}

export type WebhookTriggersArray = WebhookTrigger[];
@Injectable({
    providedIn: 'root',
})
export class WebhookTriggerNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get apiUrlTriggers(): string {
        return this.configService.apiUrl + 'webhook-triggers/';
    }

    private get apiUrlNode(): string {
        return this.configService.apiUrl + 'webhook-trigger-nodes/';
    }

    getWebhookTriggersRequest(): Observable<ApiGetRequest<WebhookTrigger>> {
        return this.http.get<ApiGetRequest<WebhookTrigger>>(this.apiUrlTriggers);
    }

    getWebhookTriggerNodeRequest(): Observable<ApiGetRequest<GetWebhookTriggerNodeRequest>> {
        return this.http.get<ApiGetRequest<GetWebhookTriggerNodeRequest>>(this.apiUrlTriggers);
    }

    createWebhookTriggerNode(request: CreateWebhookTriggerNodeRequest): Observable<Record<string, unknown>> {
        return this.http.post<Record<string, unknown>>(this.apiUrlNode, request, {
            headers: this.headers,
        });
    }

    updateWebhookTriggerNode(
        id: number,
        request: CreateWebhookTriggerNodeRequest
    ): Observable<Record<string, unknown>> {
        return this.http.put<Record<string, unknown>>(`${this.apiUrlNode}${id}/`, request, {
            headers: this.headers,
        });
    }

    deleteWebhookTriggerNode(id: string): Observable<unknown> {
        return this.http.delete<unknown>(`${this.apiUrlNode}${id}/`, {
            headers: this.headers,
        });
    }
}
