import { TestBed } from '@angular/core/testing';

import { ConversationListPreferencesService } from './conversation-list-preferences.service';

const STORAGE_KEY = 'chat:conversationList';

describe('ConversationListPreferencesService', () => {
    const preferences = (): ConversationListPreferencesService => TestBed.inject(ConversationListPreferencesService);
    const collapsed = (): string[] => [...preferences().collapsed()];

    beforeEach(() => localStorage.clear());

    afterEach(() => {
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it("collapses Tests, sorts newest first and shows everyone's conversations by default", () => {
        expect(collapsed()).toEqual(['test']);
        expect(preferences().order()).toBe('newest');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('remembers a collapse and an expand per browser', () => {
        preferences().setCollapsed('bot', true);
        preferences().setCollapsed('test', false);
        expect(collapsed()).toEqual(['bot']);
        expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({
            collapsed: ['bot'],
            order: 'newest',
            isMineOnly: false,
        });

        TestBed.resetTestingModule();
        expect(collapsed()).toEqual(['bot']);
    });

    it('remembers the sort order and Mine per browser, alongside the collapsed sections', () => {
        preferences().setOrder('oldest');
        preferences().setMineOnly(true);
        expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({
            collapsed: ['test'],
            order: 'oldest',
            isMineOnly: true,
        });

        TestBed.resetTestingModule();
        expect(preferences().order()).toBe('oldest');
        expect(preferences().isMineOnly()).toBe(true);
        expect(collapsed()).toEqual(['test']);
    });

    it('reads only known sections and values, each falling back to its own default', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ collapsed: ['bot', 'gone', 'waiting', 'bot'], order: 'sideways', isMineOnly: 'yes' })
        );
        expect(collapsed()).toEqual(['waiting', 'bot']);
        expect(preferences().order()).toBe('newest');
        expect(preferences().isMineOnly()).toBe(false);

        TestBed.resetTestingModule();
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ collapsed: 'bot', order: 'oldest' }));
        expect(collapsed()).toEqual(['test']);
        expect(preferences().order()).toBe('oldest');
    });

    it('falls back to the defaults on anything unreadable', () => {
        for (const stored of ['{not json', 'null', '"collapsed"', '[]']) {
            TestBed.resetTestingModule();
            localStorage.setItem(STORAGE_KEY, stored);
            expect(collapsed()).toEqual(['test']);
            expect(preferences().order()).toBe('newest');
            expect(preferences().isMineOnly()).toBe(false);
        }
    });

    it('works without storage: defaults first, then the choice in memory', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('denied');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('denied');
        });
        expect(collapsed()).toEqual(['test']);

        preferences().setCollapsed('waiting', true);
        preferences().setOrder('oldest');
        preferences().setMineOnly(true);
        expect(collapsed()).toEqual(['waiting', 'test']);
        expect(preferences().order()).toBe('oldest');
        expect(preferences().isMineOnly()).toBe(true);
    });
});
