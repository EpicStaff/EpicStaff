import { Location } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { provideLocationMocks, SpyLocation } from '@angular/common/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PhoneLayoutService } from '../../../core/services/phone-layout.service';
import { ToastService } from '../../../services/notifications';
import { ChatConversation } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatConversationActionsService } from './chat-conversation-actions.service';
import { ChatInboxStreamService } from './chat-inbox-stream.service';
import { OpenConversationService } from './open-conversation.service';
import { OpenConversationSyncService } from './open-conversation-sync.service';

/** A desk page, as the chat page provides both services. */
@Component({ template: '', providers: [OpenConversationService, OpenConversationSyncService] })
class DeskPageComponent {}

const row = (id: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    ({ id, binding_id: 'b-1', status: 'open', last_message_preview: id, ...overrides }) as ChatConversation;
const closed = (id: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row(id, { status: 'closed', close_reason: 'resolved', closed_at: '2026-10-10T12:00:00Z', ...overrides });

const DESK = '/chat-bindings/b-1';

describe('OpenConversationSyncService', () => {
    const conversationUpdated$ = new Subject<ChatConversation>();
    const changed$ = new Subject<ChatConversation>();
    const readyEpoch = signal(0);
    const chatApi = { getConversation: vi.fn<(id: string) => Observable<ChatConversation>>() };
    const toast = { error: vi.fn() };
    let harness: RouterTestingHarness;
    let location: SpyLocation;
    let open: OpenConversationService;
    let sync: OpenConversationSyncService;

    /** Lets the URL writes, the navigations they start and the effects land. */
    async function settle(): Promise<void> {
        TestBed.tick();
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    /** Arrives at a desk page with a conversation id in the URL, as a link or a reload does; the page sets the desk. */
    async function arrive(url: string, scope: string | null = 'b-1'): Promise<void> {
        await harness.navigateByUrl(url);
        const injector = harness.routeDebugElement!.injector;
        open = injector.get(OpenConversationService);
        sync = injector.get(OpenConversationSyncService);
        sync.setScope(scope);
        await settle();
    }

    /** The stream reconnected. */
    async function ready(): Promise<void> {
        readyEpoch.update((epoch) => epoch + 1);
        await settle();
    }

    beforeEach(async () => {
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            providers: [
                provideRouter([{ path: 'chat-bindings/:bindingId', component: DeskPageComponent }]),
                provideLocationMocks(),
                { provide: PhoneLayoutService, useValue: { isPhone: signal(false) } },
                { provide: ChatApiService, useValue: chatApi },
                { provide: ToastService, useValue: toast },
                { provide: ChatInboxStreamService, useValue: { conversationUpdated$, readyEpoch } },
                { provide: ChatConversationActionsService, useValue: { changed$ } },
            ],
        });
        location = TestBed.inject(Location) as SpyLocation;
        harness = await RouterTestingHarness.create();
        TestBed.inject(Router).setUpLocationChangeListener();
    });

    describe('a row the column found', () => {
        it("opens it when it is the desk's", async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));
            expect(open.row()?.id).toBe('c-1');
            expect(chatApi.getConversation).not.toHaveBeenCalled();
        });

        it("drops another desk's with a message, and takes any desk's on All desks", async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1', { binding_id: 'b-2' }));
            await settle();
            expect(open.row()).toBeNull();
            expect(toast.error).toHaveBeenCalledWith("Couldn't open that conversation.");
            expect(location.path()).toBe(DESK);

            await arrive(`${DESK}?conversation=c-2`, null);
            sync.resolve('c-2', row('c-2', { binding_id: 'b-2' }));
            expect(open.row()?.id).toBe('c-2');
        });
    });

    describe('an id the column cannot list', () => {
        it('is asked for once while the answer is on the way, and opens', async () => {
            await arrive(`${DESK}?conversation=c-old`);
            const answer$ = new Subject<ChatConversation>();
            chatApi.getConversation.mockReturnValueOnce(answer$);
            sync.resolve('c-old', 'missing');
            sync.resolve('c-old', 'missing');
            expect(chatApi.getConversation).toHaveBeenCalledTimes(1);
            expect(chatApi.getConversation).toHaveBeenCalledWith('c-old');

            answer$.next(closed('c-old'));
            expect(open.row()?.id).toBe('c-old');
            expect(toast.error).not.toHaveBeenCalled();
        });

        it("drops another desk's conversation the server returns, and a 404, with a message", async () => {
            await arrive(`${DESK}?conversation=c-old`);
            chatApi.getConversation.mockReturnValueOnce(of(closed('c-old', { binding_id: 'b-2' })));
            sync.resolve('c-old', 'missing');
            await settle();
            expect(open.row()).toBeNull();
            expect(location.path()).toBe(DESK);

            await arrive(`${DESK}?conversation=c-gone`);
            chatApi.getConversation.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 404 })));
            sync.resolve('c-gone', 'missing');
            await settle();
            expect(toast.error).toHaveBeenCalledTimes(2);
            expect(toast.error).toHaveBeenLastCalledWith("Couldn't open that conversation.");
            expect(location.path()).toBe(DESK);
        });

        it('keeps the link on any other failure, says so, and asks again only after the next ready', async () => {
            await arrive(`${DESK}?conversation=c-old`);
            chatApi.getConversation.mockReturnValueOnce(
                throwError(() => new HttpErrorResponse({ status: 503, error: { message: 'Chat is restarting.' } }))
            );
            sync.resolve('c-old', 'missing');
            await settle();
            expect(toast.error).toHaveBeenCalledWith('Chat is restarting.');
            expect(toast.error).not.toHaveBeenCalledWith("Couldn't open that conversation.");
            expect(location.path()).toBe(`${DESK}?conversation=c-old`);

            sync.resolve('c-old', 'missing');
            expect(chatApi.getConversation).toHaveBeenCalledTimes(1);

            await ready();
            chatApi.getConversation.mockReturnValueOnce(of(closed('c-old')));
            sync.resolve('c-old', 'missing');
            expect(chatApi.getConversation).toHaveBeenCalledTimes(2);
            expect(open.row()?.id).toBe('c-old');
        });

        it('ignores an answer for an id that is no longer the open one', async () => {
            await arrive(`${DESK}?conversation=c-old`);
            const answer$ = new Subject<ChatConversation>();
            chatApi.getConversation.mockReturnValueOnce(answer$);
            sync.resolve('c-old', 'missing');
            open.drop();
            answer$.next(closed('c-old'));
            expect(open.row()).toBeNull();
            expect(toast.error).not.toHaveBeenCalled();
        });
    });

    describe('live rows', () => {
        it("takes the desk's rows from the stream and from the actions, not another desk's", async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));

            conversationUpdated$.next(row('c-1', { last_message_preview: 'streamed' }));
            expect(open.row()?.last_message_preview).toBe('streamed');
            changed$.next(row('c-1', { last_message_preview: 'claimed' }));
            expect(open.row()?.last_message_preview).toBe('claimed');
            conversationUpdated$.next(row('c-1', { binding_id: 'b-2', last_message_preview: 'elsewhere' }));
            expect(open.row()?.last_message_preview).toBe('claimed');
        });
    });

    describe('after the stream reconnects', () => {
        it('fetches the open conversation again on every ready but the first, and follows the server', async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));
            expect(chatApi.getConversation).not.toHaveBeenCalled();

            chatApi.getConversation.mockReturnValueOnce(of(closed('c-1')));
            await ready();
            expect(chatApi.getConversation).toHaveBeenCalledWith('c-1');
            expect(open.row()?.status).toBe('closed');
        });

        it('fetches nothing without an open conversation', async () => {
            await arrive(DESK);
            await ready();
            expect(chatApi.getConversation).not.toHaveBeenCalled();
        });

        it('keeps a live row that came after the refetch was asked for', async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));
            const refetch$ = new Subject<ChatConversation>();
            chatApi.getConversation.mockReturnValueOnce(refetch$);
            await ready();

            conversationUpdated$.next(row('c-1', { last_message_preview: 'live' }));
            refetch$.next(row('c-1', { last_message_preview: 'stale' }));
            expect(open.row()?.last_message_preview).toBe('live');
        });

        it("keeps the row on another desk's answer and on a failed refetch, without a message", async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));
            chatApi.getConversation.mockReturnValueOnce(of(row('c-1', { binding_id: 'b-2', status: 'closed' })));
            await ready();
            expect(open.row()?.status).toBe('open');

            chatApi.getConversation.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
            await ready();
            expect(open.row()?.status).toBe('open');
            expect(toast.error).not.toHaveBeenCalled();
        });

        it('drops a refetch on its way when the page moves to another desk or org', async () => {
            await arrive(`${DESK}?conversation=c-1`);
            sync.resolve('c-1', row('c-1'));
            const refetch$ = new Subject<ChatConversation>();
            chatApi.getConversation.mockReturnValueOnce(refetch$);
            await ready();
            expect(refetch$.observed).toBe(true);
            sync.setScope('b-2');
            expect(refetch$.observed).toBe(false);

            sync.setScope('b-1');
            const again$ = new Subject<ChatConversation>();
            chatApi.getConversation.mockReturnValueOnce(again$);
            await ready();
            expect(again$.observed).toBe(true);
            sync.cancelRefresh();
            expect(again$.observed).toBe(false);
        });
    });
});
