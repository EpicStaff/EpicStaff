import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    ChatBinding,
    ChatBindingRequest,
    ChatConversation,
    ChatInboundRequest,
    ChatInboundResponse,
    ChatMessage,
} from '../models/chat.model';

type ListResponse<T> = T[] | ApiGetRequest<T>;

// PROTO: accepts both a plain array and a DRF page because the backend is built in parallel;
// the real version pins one shape and paginates the conversation list properly.
function unwrapList<T>(response: ListResponse<T>): T[] {
    return Array.isArray(response) ? response : response.results;
}

// Chat layer RBAC reuses the Flows resource (no separate ResourceType).
@Injectable({ providedIn: 'root' })
export class ChatApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get bindingsUrl(): string {
        return `${this.configService.apiUrl}chat-bindings/`;
    }

    private get conversationsUrl(): string {
        return `${this.configService.apiUrl}chat-conversations/`;
    }

    getBindings(): Observable<ChatBinding[]> {
        return this.http
            .get<ListResponse<ChatBinding>>(this.bindingsUrl, {
                params: new HttpParams().set('limit', '1000'),
                context: withPermission<ListResponse<ChatBinding>>(ResourceCode.Flows, ActionCode.Read, []),
            })
            .pipe(map(unwrapList));
    }

    createBinding(body: ChatBindingRequest): Observable<ChatBinding> {
        return this.http.post<ChatBinding>(this.bindingsUrl, body);
    }

    updateBinding(id: number, body: ChatBindingRequest): Observable<ChatBinding> {
        return this.http.patch<ChatBinding>(`${this.bindingsUrl}${id}/`, body);
    }

    deleteBinding(id: number): Observable<void> {
        return this.http.delete<void>(`${this.bindingsUrl}${id}/`);
    }

    sendInbound(bindingId: number, body: ChatInboundRequest): Observable<ChatInboundResponse> {
        return this.http.post<ChatInboundResponse>(`${this.bindingsUrl}${bindingId}/inbound/`, body);
    }

    getConversations(bindingId: number | null): Observable<ChatConversation[]> {
        let params = new HttpParams().set('limit', '1000');
        if (bindingId !== null) params = params.set('binding', bindingId);
        return this.http
            .get<ListResponse<ChatConversation>>(this.conversationsUrl, {
                params,
                context: withPermission<ListResponse<ChatConversation>>(ResourceCode.Flows, ActionCode.Read, []),
            })
            .pipe(map(unwrapList));
    }

    getMessages(conversationId: number): Observable<ChatMessage[]> {
        return this.http
            .get<ListResponse<ChatMessage>>(`${this.conversationsUrl}${conversationId}/messages/`)
            .pipe(map(unwrapList));
    }

    claim(conversationId: number): Observable<ChatConversation> {
        return this.http.post<ChatConversation>(`${this.conversationsUrl}${conversationId}/claim/`, {});
    }

    release(conversationId: number): Observable<ChatConversation> {
        return this.http.post<ChatConversation>(`${this.conversationsUrl}${conversationId}/release/`, {});
    }

    close(conversationId: number): Observable<ChatConversation> {
        return this.http.post<ChatConversation>(`${this.conversationsUrl}${conversationId}/close/`, {});
    }

    sendOperatorMessage(conversationId: number, content: string): Observable<ChatMessage> {
        return this.http.post<ChatMessage>(`${this.conversationsUrl}${conversationId}/operator-message/`, {
            content,
        });
    }
}
