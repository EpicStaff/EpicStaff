import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config/config.service';
import {
    FlowAssistantConfig,
    FlowAssistantConversation,
    SendMessageResponse,
    SessionSummary,
} from '../models/flow-assistant.model';

@Injectable({
    providedIn: 'root',
})
export class FlowAssistantApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private baseUrl(graphId: number): string {
        return `${this.configService.apiUrl}flow-assistants/${graphId}/`;
    }

    private conversationsUrl(graphId: number): string {
        return `${this.baseUrl(graphId)}conversations/`;
    }

    private conversationUrl(graphId: number, conversationId: number): string {
        return `${this.conversationsUrl(graphId)}${conversationId}/`;
    }

    listConversations(graphId: number): Observable<{ count: number; results: SessionSummary[] } | SessionSummary[]> {
        return this.http.get<{ count: number; results: SessionSummary[] } | SessionSummary[]>(
            this.conversationsUrl(graphId)
        );
    }

    getConfig(graphId: number): Observable<FlowAssistantConfig> {
        return this.http.get<FlowAssistantConfig>(this.baseUrl(graphId));
    }

    patchConfig(graphId: number, body: Partial<FlowAssistantConfig>): Observable<FlowAssistantConfig> {
        return this.http.patch<FlowAssistantConfig>(this.baseUrl(graphId), body);
    }

    startConversation(graphId: number): Observable<{ conversation_id: number }> {
        return this.http.post<{ conversation_id: number }>(this.conversationsUrl(graphId), {});
    }

    getConversation(graphId: number, conversationId: number): Observable<FlowAssistantConversation> {
        return this.http.get<FlowAssistantConversation>(this.conversationUrl(graphId, conversationId));
    }

    deleteConversation(graphId: number, conversationId: number): Observable<void> {
        return this.http.delete<void>(this.conversationUrl(graphId, conversationId));
    }

    sendMessage(graphId: number, conversationId: number, text: string): Observable<SendMessageResponse> {
        return this.http.post<SendMessageResponse>(`${this.conversationUrl(graphId, conversationId)}messages/`, {
            message: text,
        });
    }

    cancelConversation(graphId: number, conversationId: number): Observable<void> {
        return this.http.post<void>(`${this.conversationUrl(graphId, conversationId)}cancel/`, {});
    }
}
