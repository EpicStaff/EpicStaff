import { computed, Injectable, signal } from '@angular/core';

import { ConversationListTab, InboxSection, TestingSection } from '../utils/conversation-list-tab.util';

const STORAGE_KEY = 'chat:conversationList';
const TABS: readonly ConversationListTab[] = ['inbox', 'testing'];
const SECTIONS: readonly InboxSection[] = ['waiting', 'in_progress', 'closed', 'bot'];
const TESTING_SECTIONS: readonly TestingSection[] = ['test_bot', 'test_closed'];

/** What the conversations column remembers per browser, as one JSON object. The search is never remembered. */
interface ConversationListPreferences {
    tab: ConversationListTab;
    // Inbox's open section, and Bot Testing's: each tab remembers its own.
    expanded: InboxSection | null;
    testingExpanded: TestingSection | null;
    // Only the conversations the user holds.
    isMineOnly: boolean;
}

const defaults = (): ConversationListPreferences => ({
    tab: 'inbox',
    expanded: 'waiting',
    testingExpanded: 'test_bot',
    isMineOnly: false,
});

/**
 * The conversations column's choices, remembered per browser. Every storage access may throw (private mode, quota):
 * the choice then holds in memory only. A missing or unreadable value means its default.
 */
@Injectable({ providedIn: 'root' })
export class ConversationListPreferencesService {
    private readonly preferences = signal<ConversationListPreferences>(this.read());

    readonly tab = computed(() => this.preferences().tab);
    readonly expanded = computed(() => this.preferences().expanded);
    readonly testingExpanded = computed(() => this.preferences().testingExpanded);
    readonly isMineOnly = computed(() => this.preferences().isMineOnly);

    setTab(tab: ConversationListTab): void {
        this.save({ tab });
    }

    setExpanded(expanded: InboxSection | null): void {
        this.save({ expanded });
    }

    setTestingExpanded(testingExpanded: TestingSection | null): void {
        this.save({ testingExpanded });
    }

    setMineOnly(isMineOnly: boolean): void {
        this.save({ isMineOnly });
    }

    private save(change: Partial<ConversationListPreferences>): void {
        this.preferences.update((preferences) => ({ ...preferences, ...change }));
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(this.preferences()));
        } catch {
            // localStorage unavailable (quota exceeded, private mode): the choice still holds in memory.
        }
    }

    private read(): ConversationListPreferences {
        let stored: string | null;
        try {
            stored = localStorage.getItem(STORAGE_KEY);
        } catch {
            return defaults();
        }
        if (stored === null) return defaults();
        let value: unknown;
        try {
            value = JSON.parse(stored);
        } catch {
            return defaults();
        }
        if (!value || typeof value !== 'object') return defaults();
        const fields = value as Record<string, unknown>;
        const fallback = defaults();
        const expanded = fields['expanded'];
        const testingExpanded = fields['testingExpanded'];
        return {
            tab: TABS.find((tab) => tab === fields['tab']) ?? fallback.tab,
            // Only Inbox's sections: `test` is a tab of its own, so a stored `test` means the default.
            expanded:
                expanded === null ? null : (SECTIONS.find((section) => section === expanded) ?? fallback.expanded),
            testingExpanded:
                testingExpanded === null
                    ? null
                    : (TESTING_SECTIONS.find((section) => section === testingExpanded) ?? fallback.testingExpanded),
            isMineOnly: typeof fields['isMineOnly'] === 'boolean' ? fields['isMineOnly'] : fallback.isMineOnly,
        };
    }
}
