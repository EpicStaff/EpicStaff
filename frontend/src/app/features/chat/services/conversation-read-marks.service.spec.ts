import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ProfileService } from '../../../services/auth/profile.service';
import { ChatConversation } from '../models/chat.model';
import { ConversationReadMarksService } from './conversation-read-marks.service';

const ME = 3;
const COLLEAGUE = 7;
const BEFORE_MARKS = '2026-10-01T10:00:00.000Z';
const MARKS_BEGIN = '2026-10-12T10:00:00.000Z';
const LATER = '2026-10-12T11:00:00.000Z';
const LATEST = '2026-10-12T12:00:00.000Z';
const storageKey = (userId: number): string => `chat:readMarks:${userId}`;

const conversation = (overrides: Partial<ChatConversation> = {}): ChatConversation =>
    ({
        id: 'c-1',
        last_message_at: LATER,
        last_message_author_user_id: COLLEAGUE,
        ...overrides,
    }) as ChatConversation;

describe('ConversationReadMarksService', () => {
    let currentUser: WritableSignal<{ id: number } | null>;
    const marks = (): ConversationReadMarksService => TestBed.inject(ConversationReadMarksService);

    beforeEach(() => {
        localStorage.clear();
        vi.useFakeTimers({ toFake: ['Date'] });
        vi.setSystemTime(new Date(MARKS_BEGIN));
        currentUser = signal<{ id: number } | null>({ id: ME });
        TestBed.configureTestingModule({
            providers: [{ provide: ProfileService, useValue: { currentUserSignal: currentUser } }],
        });
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it('counts what was written before marks began as read, so a first visit lights up nothing old', () => {
        expect(marks().isUnread(conversation({ last_message_at: BEFORE_MARKS }))).toBe(false);
        expect(marks().isUnread(conversation({ last_message_at: LATER }))).toBe(true);
    });

    it('reads a conversation up to its last message, until a newer one comes', () => {
        marks().markRead(conversation({ last_message_at: LATER }));
        expect(marks().isUnread(conversation({ last_message_at: LATER }))).toBe(false);
        expect(marks().isUnread(conversation({ last_message_at: LATEST }))).toBe(true);
    });

    it("never counts the user's own last message as news", () => {
        expect(marks().isUnread(conversation({ last_message_author_user_id: ME }))).toBe(false);
    });

    it('has no news without a message, or without a user', () => {
        expect(marks().isUnread(conversation({ last_message_at: null }))).toBe(false);
        currentUser.set(null);
        expect(marks().isUnread(conversation())).toBe(false);
    });

    it('remembers the marks per browser and per user', () => {
        marks().markRead(conversation());
        expect(JSON.parse(localStorage.getItem(storageKey(ME))!)).toEqual({
            since: MARKS_BEGIN,
            seen: { 'c-1': LATER },
        });

        currentUser.set({ id: COLLEAGUE });
        expect(marks().isUnread(conversation({ last_message_author_user_id: ME }))).toBe(true);

        currentUser.set({ id: ME });
        expect(marks().isUnread(conversation())).toBe(false);
    });

    it('begins afresh from a value it cannot read', () => {
        localStorage.setItem(storageKey(ME), JSON.stringify({ since: 'never', seen: [] }));
        expect(marks().isUnread(conversation({ last_message_at: BEFORE_MARKS }))).toBe(false);
        expect(JSON.parse(localStorage.getItem(storageKey(ME))!).since).toBe(MARKS_BEGIN);
    });

    it('keeps only the newest 500 marks, and what it drops stays read', () => {
        const at = (index: number): string => new Date(Date.parse(LATER) + index * 1000).toISOString();
        for (let index = 0; index < 501; index++) {
            marks().markRead(conversation({ id: `c-${index}`, last_message_at: at(index) }));
        }
        const seen = JSON.parse(localStorage.getItem(storageKey(ME))!).seen as Record<string, string>;
        expect(Object.keys(seen)).toHaveLength(500);
        expect(seen['c-0']).toBeUndefined();
        expect(seen['c-500']).toBeDefined();
        expect(marks().isUnread(conversation({ id: 'c-0', last_message_at: at(0) }))).toBe(false);
        expect(marks().isUnread(conversation({ id: 'c-0', last_message_at: LATEST }))).toBe(true);
    });

    it("keeps another tab's marks when it writes its own", () => {
        marks();
        localStorage.setItem(storageKey(ME), JSON.stringify({ since: MARKS_BEGIN, seen: { 'c-other': LATER } }));
        marks().markRead(conversation({ id: 'c-1' }));
        expect(JSON.parse(localStorage.getItem(storageKey(ME))!).seen).toEqual({ 'c-other': LATER, 'c-1': LATER });
        expect(marks().isUnread(conversation({ id: 'c-other' }))).toBe(false);
    });

    it('shows at once what another tab marked read', () => {
        expect(marks().isUnread(conversation())).toBe(true);
        const stored = JSON.stringify({ since: MARKS_BEGIN, seen: { 'c-1': LATER } });
        localStorage.setItem(storageKey(ME), stored);
        window.dispatchEvent(new StorageEvent('storage', { key: storageKey(ME), newValue: stored }));
        expect(marks().isUnread(conversation())).toBe(false);
    });

    it('still works in memory when the storage throws', () => {
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('QuotaExceededError');
        });
        marks().markRead(conversation());
        expect(marks().isUnread(conversation())).toBe(false);
    });
});
