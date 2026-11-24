import { computed, Injectable, signal } from '@angular/core';

import { ConversationListTab, InboxSection, TestingSection } from '../utils/conversation-list-tab.util';

const STORAGE_KEY = 'chat:conversationList';
const TABS: readonly ConversationListTab[] = ['inbox', 'testing'];
// In column order, which is the order they are stored in.
const SECTIONS: readonly InboxSection[] = ['waiting', 'in_progress', 'bot', 'closed'];
const TESTING_SECTIONS: readonly TestingSection[] = ['test_open', 'test_closed'];

/** What the conversations column remembers per browser, as one JSON object. The search is never remembered. */
interface ConversationListPreferences {
    tab: ConversationListTab;
    // Inbox's open sections, and Bot Testing's: each tab remembers its own; empty when every one is folded.
    openSections: readonly InboxSection[];
    openTestingSections: readonly TestingSection[];
    // Only the conversations the user holds.
    isMineOnly: boolean;
}

const defaults = (): ConversationListPreferences => ({
    tab: 'inbox',
    openSections: SECTIONS,
    openTestingSections: TESTING_SECTIONS,
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
    /** Inbox's open sections, in column order. */
    readonly openSections = computed(() => this.preferences().openSections);
    /** Bot Testing's open sections, in column order. */
    readonly openTestingSections = computed(() => this.preferences().openTestingSections);
    readonly isMineOnly = computed(() => this.preferences().isMineOnly);

    setTab(tab: ConversationListTab): void {
        this.save({ tab });
    }

    setOpenSections(sections: readonly InboxSection[]): void {
        this.save({ openSections: inColumnOrder(SECTIONS, sections) });
    }

    setOpenTestingSections(sections: readonly TestingSection[]): void {
        this.save({ openTestingSections: inColumnOrder(TESTING_SECTIONS, sections) });
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

    /**
     * Fields this version does not know are ignored, so a value saved when one section was open at a time (its
     * `expanded`) opens every section, and keeps the rest of it.
     */
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
        return {
            tab: TABS.find((tab) => tab === fields['tab']) ?? fallback.tab,
            openSections: readSections(SECTIONS, fields['openSections']) ?? fallback.openSections,
            openTestingSections:
                readSections(TESTING_SECTIONS, fields['openTestingSections']) ?? fallback.openTestingSections,
            isMineOnly: typeof fields['isMineOnly'] === 'boolean' ? fields['isMineOnly'] : fallback.isMineOnly,
        };
    }
}

/** A stored list of sections: the known ones in it, in column order; null when it is no list at all. */
function readSections<T extends string>(known: readonly T[], value: unknown): readonly T[] | null {
    return Array.isArray(value) ? inColumnOrder(known, value) : null;
}

// Each section once, in column order; anything else is dropped.
function inColumnOrder<T extends string>(known: readonly T[], sections: readonly unknown[]): readonly T[] {
    return known.filter((section) => sections.includes(section));
}
