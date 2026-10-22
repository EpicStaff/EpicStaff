import { Location } from '@angular/common';
import { provideLocationMocks, SpyLocation } from '@angular/common/testing';
import { Component, inject, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { PhoneLayoutService } from '../../../core/services/phone-layout.service';
import { ChatConversation } from '../models/chat.model';
import { OpenConversationService, THREAD_ENTRY_STATE, URL_WRITE_DELAY_MS } from './open-conversation.service';

/** A desk page, as the chat page provides the service. */
@Component({ template: '', providers: [OpenConversationService] })
class DeskPageComponent {
    readonly openConversation = inject(OpenConversationService);
}

@Component({ template: '' })
class OtherPageComponent {}

const conversation = (id: string, preview = 'hello'): ChatConversation =>
    ({ id, binding_id: 'b-1', last_message_preview: preview }) as ChatConversation;

const LIST = '/chat-bindings/all';

describe('OpenConversationService', () => {
    const isPhone = signal(false);
    let harness: RouterTestingHarness;
    let location: SpyLocation;
    let service: OpenConversationService;

    const isThreadEntry = (): boolean =>
        (location.getState() as Record<string, unknown> | null)?.[THREAD_ENTRY_STATE] === true;

    /** Lets the URL writes and the navigations they start land. */
    async function settle(): Promise<void> {
        await harness.fixture.whenStable();
        harness.detectChanges();
    }

    /** A move through history (Safari's edge swipe, Android's back): the router takes it up a macrotask later. */
    async function historyMove(move: () => void): Promise<void> {
        move();
        await new Promise((resolve) => setTimeout(resolve));
        await settle();
    }

    /** Waits out the wider screens' write delay. */
    async function rest(): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve, URL_WRITE_DELAY_MS));
        await settle();
    }

    /** Arrives at a URL the way a link, a reload or history would: by navigation, not through the service. */
    async function arrive(url: string, state?: Record<string, unknown>): Promise<void> {
        await harness.navigateByUrl(url);
        if (state) location.replaceState(location.path(), '', { ...(location.getState() as object), ...state });
        service = harness.routeDebugElement!.injector.get(OpenConversationService);
    }

    beforeEach(async () => {
        isPhone.set(false);
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { path: 'chat-bindings/:bindingId', component: DeskPageComponent },
                    { path: 'agents', component: OtherPageComponent },
                ]),
                provideLocationMocks(),
                { provide: PhoneLayoutService, useValue: { isPhone } },
            ],
        });
        location = TestBed.inject(Location) as SpyLocation;
        harness = await RouterTestingHarness.create();
        // As the app's initial navigation does: back and forward reach the router.
        TestBed.inject(Router).setUpLocationChangeListener();
        await arrive(LIST);
        location.urlChanges = [];
    });

    describe('on wider screens', () => {
        it('shows each open at once and writes the URL once the selection rests, replacing the entry', async () => {
            service.open(conversation('c-1'));
            service.open(conversation('c-2'));
            service.open(conversation('c-3'));

            expect(service.id()).toBe('c-3');
            expect(service.row()?.id).toBe('c-3');
            expect(location.urlChanges).toEqual([]);

            await new Promise((resolve) => setTimeout(resolve, URL_WRITE_DELAY_MS / 2));
            expect(location.urlChanges).toEqual([]);

            await rest();
            expect(location.urlChanges).toEqual([`replace: ${LIST}?conversation=c-3`]);
            expect(service.urlId()).toBe('c-3');
            expect(service.id()).toBe('c-3');
            expect(isThreadEntry()).toBe(false);
        });

        it('drops a write not made yet when a navigation made elsewhere (a link) comes first', async () => {
            service.open(conversation('c-1'));
            await harness.navigateByUrl('/chat-bindings/b-2');
            await rest();

            expect(location.path()).toBe('/chat-bindings/b-2');
            expect(service.id()).toBeNull();
        });

        it('takes the id out of the URL in place on drop, and keeps the URL id on forget', async () => {
            await arrive(`${LIST}?conversation=c-1`);
            service.remember(conversation('c-1'));
            location.urlChanges = [];

            service.forget();
            expect(service.id()).toBe('c-1');
            expect(service.row()).toBeNull();

            service.drop();
            expect(service.id()).toBeNull();
            await settle();
            expect(location.urlChanges).toEqual([`replace: ${LIST}`]);
        });

        it("keeps only the open conversation's newer rows, and forgets the row once the conversation closes", async () => {
            service.open(conversation('c-1', 'old'));
            service.remember(conversation('c-2', 'other'));
            service.remember(conversation('c-1', 'new'));
            expect(service.row()?.last_message_preview).toBe('new');

            await rest();
            service.drop();
            await settle();
            // History forward to it later takes the list's fresh row, not this one.
            await arrive(`${LIST}?conversation=c-1`);
            expect(service.id()).toBe('c-1');
            expect(service.row()).toBeNull();
        });
    });

    describe('on a phone', () => {
        beforeEach(() => isPhone.set(true));

        it('pushes a thread entry when a conversation opens from the list, and slides it in', async () => {
            service.open(conversation('c-1'));
            expect(service.isStackAnimated()).toBe(true);
            await settle();

            expect(location.urlChanges).toEqual([`${LIST}?conversation=c-1`]);
            expect(isThreadEntry()).toBe(true);
        });

        it('replaces the thread shown, keeping its mark, without a slide', async () => {
            service.open(conversation('c-1'));
            await settle();
            service.stackSlid();

            service.open(conversation('c-2'));
            await settle();

            expect(location.urlChanges.at(-1)).toBe(`replace: ${LIST}?conversation=c-2`);
            expect(isThreadEntry()).toBe(true);
            expect(service.isStackAnimated()).toBe(false);
        });

        it('goes back through history from a thread it pushed, once however often Back is tapped, and slides', async () => {
            service.open(conversation('c-1'));
            await settle();
            service.stackSlid();

            service.close();
            service.close();
            expect(service.id()).toBeNull();
            await historyMove(() => undefined);

            expect(location.path()).toBe(LIST);
            expect(service.isStackAnimated()).toBe(true);
            // Back once, onto the list's entry: nothing before it was left.
            await historyMove(() => location.forward());
            expect(location.path()).toBe(`${LIST}?conversation=c-1`);
            expect(service.id()).toBe('c-1');
        });

        it('keeps a row tapped right after Back: it shows at once and is pushed from the list once the Back has landed', async () => {
            service.open(conversation('c-1'));
            await settle();

            service.close();
            // Before the router has taken the Back up: the URL and the history entry are still the thread's.
            service.open(conversation('c-2'));
            expect(service.id()).toBe('c-2');
            expect(service.row()?.id).toBe('c-2');

            await historyMove(() => undefined);

            expect(location.path()).toBe(`${LIST}?conversation=c-2`);
            expect(service.urlId()).toBe('c-2');
            expect(isThreadEntry()).toBe(true);
            expect(location.urlChanges).toEqual([`${LIST}?conversation=c-1`, `${LIST}?conversation=c-2`]);
            // Its own entry over the list's: back returns to the list.
            await historyMove(() => location.back());
            expect(location.path()).toBe(LIST);
            expect(service.id()).toBeNull();
        });

        it('keeps the same conversation tapped again right after Back open, without a flash closed', async () => {
            service.open(conversation('c-1'));
            await settle();

            service.close();
            // The URL still names c-1 until the Back lands: that must not count as c-1 written.
            service.open(conversation('c-1'));
            harness.detectChanges();
            expect(service.id()).toBe('c-1');

            await historyMove(() => undefined);

            expect(service.id()).toBe('c-1');
            expect(service.row()?.id).toBe('c-1');
            expect(location.path()).toBe(`${LIST}?conversation=c-1`);
            expect(isThreadEntry()).toBe(true);
        });

        it('takes a Back that the router skips (onto an entry with the same URL) as landed', async () => {
            await arrive(`${LIST}?conversation=c-1`);
            service.remember(conversation('c-1'));
            // A thread entry over another entry with the very same URL.
            location.go(location.path(), '', { ...(location.getState() as object), [THREAD_ENTRY_STATE]: true });
            location.urlChanges = [];

            service.close();
            await historyMove(() => undefined);

            // The URL said c-1 still: it loses it in place, so it says the list the user sees.
            expect(location.urlChanges).toEqual([`replace: ${LIST}`]);
            expect(service.id()).toBeNull();
            // And the next tap is written at once, not held for a Back that will never land.
            service.open(conversation('c-2'));
            await settle();
            expect(location.urlChanges.at(-1)).toBe(`${LIST}?conversation=c-2`);
        });

        it('opens nothing when Back follows a row tapped while the first Back was on its way', async () => {
            service.open(conversation('c-1'));
            await settle();

            service.close();
            service.open(conversation('c-2'));
            service.close();
            expect(service.id()).toBeNull();

            await historyMove(() => undefined);
            expect(location.path()).toBe(LIST);
            expect(service.id()).toBeNull();
            expect(location.urlChanges).toEqual([`${LIST}?conversation=c-1`]);
        });

        it("closes on a move through history without a slide: Safari's edge swipe animated it already", async () => {
            service.open(conversation('c-1'));
            await settle();

            await historyMove(() => location.back());

            expect(service.id()).toBeNull();
            expect(service.row()).toBeNull();
            expect(service.isStackAnimated()).toBe(false);
        });

        it('drops the id in place from a thread it did not push (a link, a reload)', async () => {
            await arrive(`${LIST}?conversation=c-1`);
            service.remember(conversation('c-1'));
            location.urlChanges = [];

            service.close();
            await settle();

            expect(location.urlChanges).toEqual([`replace: ${LIST}`]);
            expect(service.id()).toBeNull();
        });

        it('pushes from the list while the URL names a conversation the list never resolved, with that id gone from the entry below', async () => {
            await arrive(`${LIST}?conversation=c-gone`);
            location.urlChanges = [];

            // The list is on screen: c-gone has no row.
            service.open(conversation('c-1'));
            await settle();

            expect(location.urlChanges).toEqual([`replace: ${LIST}`, `${LIST}?conversation=c-1`]);
            expect(isThreadEntry()).toBe(true);
            await historyMove(() => location.back());
            expect(location.path()).toBe(LIST);
            expect(service.id()).toBeNull();
        });

        it('replaces a reloaded thread entry whose conversation the list never resolved: it is the thread entry already', async () => {
            await arrive(`${LIST}?conversation=c-gone`, { [THREAD_ENTRY_STATE]: true });
            location.urlChanges = [];

            service.open(conversation('c-1'));
            expect(service.isStackAnimated()).toBe(true);
            await settle();

            expect(location.urlChanges).toEqual([`replace: ${LIST}?conversation=c-1`]);
            expect(isThreadEntry()).toBe(true);
        });
    });
});
