import { TestBed } from '@angular/core/testing';

import { ConversationListPreferencesService } from './conversation-list-preferences.service';

const STORAGE_KEY = 'chat:conversationList';

describe('ConversationListPreferencesService', () => {
    const preferences = (): ConversationListPreferencesService => TestBed.inject(ConversationListPreferencesService);

    const readAgain = (): ConversationListPreferencesService => new ConversationListPreferencesService();

    beforeEach(() => localStorage.clear());

    afterEach(() => {
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it("opens Inbox at Waiting, Bot Testing at its open tests, and shows everyone's conversations by default", () => {
        expect(preferences().tab()).toBe('inbox');
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().testingExpanded()).toBe('test_open');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('remembers the open section per browser', () => {
        preferences().setExpanded('bot');
        expect(preferences().expanded()).toBe('bot');
        expect(readAgain().expanded()).toBe('bot');
    });

    it('remembers that no section is open', () => {
        preferences().setExpanded(null);
        expect(readAgain().expanded()).toBeNull();
    });

    it("remembers the tab, each tab's open section and Mine together", () => {
        preferences().setTab('testing');
        preferences().setExpanded('closed');
        preferences().setTestingExpanded('test_closed');
        preferences().setMineOnly(true);

        const again = readAgain();
        expect(again.tab()).toBe('testing');
        expect(again.expanded()).toBe('closed');
        expect(again.testingExpanded()).toBe('test_closed');
        expect(again.isMineOnly()).toBe(true);
    });

    it('opens Waiting for a value saved before one open section was remembered, keeping the rest of it', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ collapsed: ['bot'], order: 'oldest', isMineOnly: true, known: ['waiting', 'bot'] })
        );
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().isMineOnly()).toBe(true);
    });

    // `test` is no Inbox section to open: tests are a tab of their own.
    it('reads only known values, each falling back to its own default', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ tab: 'tests', expanded: 'test', testingExpanded: 'test_bot', isMineOnly: 'yes' })
        );
        expect(preferences().tab()).toBe('inbox');
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().testingExpanded()).toBe('test_open');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('keeps a known value beside unknown ones', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ expanded: 'closed', isMineOnly: 42 }));
        expect(preferences().expanded()).toBe('closed');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it.each(['{not json', 'null', '"expanded"', '[]'])('falls back to the defaults on %s', (value) => {
        localStorage.setItem(STORAGE_KEY, value);
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('works without storage: defaults first, then the choice in memory', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('denied');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('denied');
        });
        expect(preferences().expanded()).toBe('waiting');

        preferences().setExpanded(null);
        preferences().setMineOnly(true);
        expect(preferences().expanded()).toBeNull();
        expect(preferences().isMineOnly()).toBe(true);
    });
});
