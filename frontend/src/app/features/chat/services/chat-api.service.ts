import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { SKIP_AUTH_HEADER_OVERRIDE } from '../../../core/interceptors/skip-auth-header-override.context';
import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import {
    ChatBinding,
    ChatBindingInput,
    ChatBindingLimits,
    ChatBindingPatch,
    ChatBindingWithSecret,
    ChatContractCheck,
    ChatConversation,
    ChatConversationPage,
    ChatInboxSection,
    ChatMode,
    ChatOperatorMessage,
    ChatSendResult,
    ChatSnippet,
    ChatTestConversation,
    ChatTicket,
    ChatVisitorMessageExtras,
} from '../models/chat.model';

export const CHAT_MESSAGES_PAGE_SIZE = 50;

export interface ConversationListParams {
    section: ChatInboxSection;
    binding: string | null;
    // Narrows the human section only; the server refuses it with the bot section.
    mode?: Exclude<ChatMode, 'bot'>;
    cursor?: string | null;
}

/** HTTP only (no state). Operator routes get the JWT and org header from the app interceptors;
 *  public routes are called as the widget would, with the conversation's visitor token. */
@Injectable({ providedIn: 'root' })
export class ChatApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get operatorUrl(): string {
        return `${this.configService.chatApiUrl}operator/v1/`;
    }

    private get publicUrl(): string {
        return `${this.configService.chatApiUrl}public/v1/`;
    }

    // ---- bindings ----

    getBindings(): Observable<ChatBinding[]> {
        return this.http.get<ChatBinding[]>(`${this.operatorUrl}bindings`);
    }

    getBindingLimits(): Observable<ChatBindingLimits> {
        return this.http.get<ChatBindingLimits>(`${this.operatorUrl}bindings/limits`);
    }

    /** 400 `unknown_flow` when the flow does not exist in the org. */
    checkContract(graphId: number): Observable<ChatContractCheck> {
        return this.http.get<ChatContractCheck>(`${this.operatorUrl}bindings/contract`, {
            params: new HttpParams().set('graph_id', graphId),
        });
    }

    /** A save whose flow fails the contract still succeeds: it returns the binding paused, with its errors. */
    createBinding(body: ChatBindingInput): Observable<ChatBindingWithSecret> {
        return this.http.post<ChatBindingWithSecret>(`${this.operatorUrl}bindings`, body);
    }

    /** `identity_secret` is present only when the patch switched `identity_mode` to `signed`. */
    updateBinding(id: string, patch: ChatBindingPatch): Observable<ChatBinding | ChatBindingWithSecret> {
        return this.http.patch<ChatBinding | ChatBindingWithSecret>(`${this.operatorUrl}bindings/${id}`, patch);
    }

    pauseBinding(id: string): Observable<ChatBinding> {
        return this.http.post<ChatBinding>(`${this.operatorUrl}bindings/${id}/pause`, {});
    }

    /** Re-checks the contract: 400 `contract_failed` or `unknown_flow` leaves the binding paused. */
    resumeBinding(id: string): Observable<ChatBinding> {
        return this.http.post<ChatBinding>(`${this.operatorUrl}bindings/${id}/resume`, {});
    }

    deleteBinding(id: string): Observable<void> {
        return this.http.delete<void>(`${this.operatorUrl}bindings/${id}`);
    }

    rotateKey(id: string): Observable<ChatBinding> {
        return this.http.post<ChatBinding>(`${this.operatorUrl}bindings/${id}/rotate-key`, {});
    }

    getSnippet(id: string): Observable<ChatSnippet> {
        return this.http.get<ChatSnippet>(`${this.operatorUrl}bindings/${id}/snippet`);
    }

    createTestConversation(bindingId: string): Observable<ChatTestConversation> {
        return this.http.post<ChatTestConversation>(`${this.operatorUrl}bindings/${bindingId}/test-conversation`, {});
    }

    /** A fresh visitor token for an existing test conversation (400 `not_a_test_conversation` otherwise). */
    issueVisitorToken(conversationId: string): Observable<{ visitor_token: string }> {
        return this.http.post<{ visitor_token: string }>(
            `${this.operatorUrl}conversations/${conversationId}/visitor-token`,
            {}
        );
    }

    // ---- inbox ----

    getInboxTicket(): Observable<ChatTicket> {
        return this.http.post<ChatTicket>(`${this.operatorUrl}inbox/stream-ticket`, {});
    }

    inboxStreamUrl(ticket: string): string {
        return `${this.operatorUrl}inbox/stream?ticket=${encodeURIComponent(ticket)}`;
    }

    getConversations(params: ConversationListParams): Observable<ChatConversationPage> {
        let httpParams = new HttpParams().set('section', params.section);
        if (params.cursor) httpParams = httpParams.set('cursor', params.cursor);
        if (params.binding) httpParams = httpParams.set('binding', params.binding);
        if (params.mode) httpParams = httpParams.set('mode', params.mode);
        return this.http.get<ChatConversationPage>(`${this.operatorUrl}conversations`, { params: httpParams });
    }

    /** Newest page, oldest first; `before` pages backward from a message id. */
    getMessages(conversationId: string, before: string | null = null): Observable<ChatOperatorMessage[]> {
        let httpParams = new HttpParams().set('limit', CHAT_MESSAGES_PAGE_SIZE);
        if (before) httpParams = httpParams.set('before', before);
        return this.http.get<ChatOperatorMessage[]>(`${this.operatorUrl}conversations/${conversationId}/messages`, {
            params: httpParams,
        });
    }

    claim(conversationId: string, force = false): Observable<ChatConversation> {
        return this.http.post<ChatConversation>(`${this.operatorUrl}conversations/${conversationId}/claim`, { force });
    }

    release(conversationId: string): Observable<ChatConversation> {
        return this.http.post<ChatConversation>(`${this.operatorUrl}conversations/${conversationId}/release`, {});
    }

    reply(conversationId: string, content: string): Observable<ChatOperatorMessage> {
        return this.http.post<ChatOperatorMessage>(`${this.operatorUrl}conversations/${conversationId}/messages`, {
            content,
        });
    }

    // ---- public widget contract, used by the simulate panel ----

    sendAsVisitor(
        conversationId: string,
        visitorToken: string,
        content: string,
        extras: ChatVisitorMessageExtras = {}
    ): Observable<ChatSendResult> {
        const body: ChatVisitorMessageExtras & { content: string } = { content };
        if (extras.action) body.action = extras.action;
        if (extras.chat_extra_data) body.chat_extra_data = extras.chat_extra_data;
        return this.http.post<ChatSendResult>(
            `${this.publicUrl}conversations/${conversationId}/messages`,
            body,
            this.asVisitor(visitorToken)
        );
    }

    /** The visitor token replaces the user JWT, and a public 401/403 is the widget's problem, not a session problem. */
    private asVisitor(visitorToken: string): { headers: Record<string, string>; context: HttpContext } {
        return {
            headers: { Authorization: `Bearer ${visitorToken}` },
            context: new HttpContext().set(SKIP_AUTH_HEADER_OVERRIDE, true).set(SKIP_FORBIDDEN_RELOAD, true),
        };
    }
}
