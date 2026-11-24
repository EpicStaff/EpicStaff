import { TestBed } from '@angular/core/testing';

import { ConversationListPreferencesService } from './conversation-list-preferences.service';

const STORAGE_KEY = 'chat:conversationList';

describe('ConversationListPreferencesService', () => {
    const preferences = (): ConversationListPreferencesService => TestBed.inject(ConversationListPreferencesService);

    const readAgain = (): ConversationListPreferencesService => new ConversationListPreferencesService();

    const store = (value: unknown): void => localStorage.setItem(STORAGE_KEY, JSON.stringify(value));

    beforeEach(() => localStorage.clear());

    afterEach(() => {
        vi.restoreAllMocks();
        localStorage.clear();
    });

    it("opens Inbox with every section open, Bot Testing too, and shows everyone's conversations by default", () => {
        expect(preferences().tab()).toBe('inbox');
        expect(preferences().openSections()).toEqual(['waiting', 'in_progress', 'bot', 'closed']);
        expect(preferences().openTestingSections()).toEqual(['test_open', 'test_closed']);
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('remembers several open sections per browser, in column order', () => {
        preferences().setOpenSections(['closed', 'waiting']);
        expect(preferences().openSections()).toEqual(['waiting', 'closed']);
        expect(readAgain().openSections()).toEqual(['waiting', 'closed']);
    });

    it('remembers that every section is folded', () => {
        preferences().setOpenSections([]);
        preferences().setOpenTestingSections([]);
        expect(readAgain().openSections()).toEqual([]);
        expect(readAgain().openTestingSections()).toEqual([]);
    });

    it("remembers the tab, each tab's open sections and Mine together", () => {
        preferences().setTab('testing');
        preferences().setOpenSections(['in_progress']);
        preferences().setOpenTestingSections(['test_closed']);
        preferences().setMineOnly(true);

        const again = readAgain();
        expect(again.tab()).toBe('testing');
        expect(again.openSections()).toEqual(['in_progress']);
        expect(again.openTestingSections()).toEqual(['test_closed']);
        expect(again.isMineOnly()).toBe(true);
    });

    it('opens every section for a value saved when one section was open at a time, keeping the rest of it', () => {
        store({ tab: 'testing', expanded: 'bot', testingExpanded: 'test_closed', isMineOnly: true });

        expect(preferences().openSections()).toEqual(['waiting', 'in_progress', 'bot', 'closed']);
        expect(preferences().openTestingSections()).toEqual(['test_open', 'test_closed']);
        expect(preferences().tab()).toBe('testing');
        expect(preferences().isMineOnly()).toBe(true);
    });

    it('drops the old single open section once a choice is saved', () => {
        store({ expanded: 'bot', isMineOnly: true });
        preferences().setMineOnly(false);
        expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).not.toHaveProperty('expanded');
    });

    // `test` is no Inbox section to open: tests are a tab of their own.
    it.each([
        { stored: ['bot', 'test', 'bot', 7, null], inbox: ['bot'] },
        { stored: ['test_open'], inbox: [] },
    ])('keeps only the known Inbox sections of $stored, each once', ({ stored, inbox }) => {
        store({ openSections: stored });
        expect(preferences().openSections()).toEqual(inbox);
    });

    it.each([null, 'waiting', { waiting: true }, 3])('opens every section for a stored list that is %j', (stored) => {
        store({ openSections: stored, openTestingSections: stored });
        expect(preferences().openSections()).toEqual(['waiting', 'in_progress', 'bot', 'closed']);
        expect(preferences().openTestingSections()).toEqual(['test_open', 'test_closed']);
    });

    it('reads only known values, each falling back to its own default', () => {
        store({ tab: 'tests', openTestingSections: ['test_bot', 'test_open'], isMineOnly: 'yes' });
        expect(preferences().tab()).toBe('inbox');
        expect(preferences().openTestingSections()).toEqual(['test_open']);
        expect(preferences().isMineOnly()).toBe(false);
    });

    it.each(['{not json', 'null', '"expanded"', '[]'])('falls back to the defaults on %s', (value) => {
        localStorage.setItem(STORAGE_KEY, value);
        expect(preferences().openSections()).toEqual(['waiting', 'in_progress', 'bot', 'closed']);
        expect(preferences().isMineOnly()).toBe(false);
    });

    it('works without storage: defaults first, then the choice in memory', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('denied');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('denied');
        });
        expect(preferences().openSections()).toEqual(['waiting', 'in_progress', 'bot', 'closed']);

        preferences().setOpenSections([]);
        preferences().setMineOnly(true);
        expect(preferences().openSections()).toEqual([]);
        expect(preferences().isMineOnly()).toBe(true);
    });
});
