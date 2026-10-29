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

    it("opens Waiting for a person only, sorts newest first and shows everyone's conversations by default", () => {
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().order()).toBe('newest');
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

    it('remembers the open section, the sort order and Mine together', () => {
        preferences().setExpanded('closed');
        preferences().setOrder('oldest');
        preferences().setMineOnly(true);

        const again = readAgain();
        expect(again.expanded()).toBe('closed');
        expect(again.order()).toBe('oldest');
        expect(again.isMineOnly()).toBe(true);
    });

    it('opens Waiting for a value saved before one open section was remembered, keeping the rest of it', () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ collapsed: ['bot'], order: 'oldest', isMineOnly: true, known: ['waiting', 'bot'] })
        );
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().order()).toBe('oldest');
        expect(preferences().isMineOnly()).toBe(true);
    });

    it('reads only known values, each falling back to its own default', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ expanded: 'gone', order: 'sideways', isMineOnly: 'yes' }));
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().order()).toBe('newest');
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('keeps a known value beside unknown ones', () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ expanded: 'test', order: 42 }));
        expect(preferences().expanded()).toBe('test');
        expect(preferences().order()).toBe('newest');
    });

    it.each(['{not json', 'null', '"expanded"', '[]'])('falls back to the defaults on %s', (value) => {
        localStorage.setItem(STORAGE_KEY, value);
        expect(preferences().expanded()).toBe('waiting');
        expect(preferences().order()).toBe('newest');
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
        preferences().setOrder('oldest');
        preferences().setMineOnly(true);
        expect(preferences().expanded()).toBeNull();
        expect(preferences().order()).toBe('oldest');
        expect(preferences().isMineOnly()).toBe(true);
    });
});
