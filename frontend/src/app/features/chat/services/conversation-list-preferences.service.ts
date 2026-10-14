import { computed, Injectable, signal } from '@angular/core';

import { ChatInboxOrder, ChatInboxSection } from '../models/chat.model';

const STORAGE_KEY = 'chat:conversationList';
const SECTIONS: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'test', 'closed', 'bot'];
const ORDERS: readonly ChatInboxOrder[] = ['newest', 'oldest'];
// Tests and Closed are there to look into, not to work through.
const DEFAULT_COLLAPSED: readonly ChatInboxSection[] = ['test', 'closed'];
// The sections a value stored before `known` existed had a say on: Closed came later, so it takes its default there.
const SECTIONS_BEFORE_KNOWN: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'test', 'bot'];

/** What the conversations column remembers per browser, as one JSON object. The search is never remembered. */
interface ConversationListPreferences {
    collapsed: ChatInboxSection[];
    order: ChatInboxOrder;
    // Only the conversations the user holds.
    isMineOnly: boolean;
}

/**
 * As stored: with the sections that existed when it was saved. `collapsed` speaks for those only, so a section added
 * later takes its default (collapsed or not) instead of reading as one the user opened.
 */
interface StoredPreferences extends ConversationListPreferences {
    known: readonly ChatInboxSection[];
}

const defaults = (): ConversationListPreferences => ({
    collapsed: [...DEFAULT_COLLAPSED],
    order: 'newest',
    isMineOnly: false,
});

/**
 * The conversations column's choices, remembered per browser. Every storage access may throw (private mode, quota):
 * the choice then holds in memory only. A missing or unreadable value means its default.
 */
@Injectable({ providedIn: 'root' })
export class ConversationListPreferencesService {
    private readonly preferences = signal<ConversationListPreferences>(this.read());

    readonly collapsed = computed((): ReadonlySet<ChatInboxSection> => new Set(this.preferences().collapsed));
    /** In progress, Tests and Bot; Waiting is always longest wait first, Closed most recently closed first. */
    readonly order = computed(() => this.preferences().order);
    readonly isMineOnly = computed(() => this.preferences().isMineOnly);

    setCollapsed(section: ChatInboxSection, collapsed: boolean): void {
        const sections = new Set(this.preferences().collapsed);
        if (collapsed) sections.add(section);
        else sections.delete(section);
        this.save({ collapsed: SECTIONS.filter((item) => sections.has(item)) });
    }

    setOrder(order: ChatInboxOrder): void {
        this.save({ order });
    }

    setMineOnly(isMineOnly: boolean): void {
        this.save({ isMineOnly });
    }

    private save(change: Partial<ConversationListPreferences>): void {
        this.preferences.update((preferences) => ({ ...preferences, ...change }));
        try {
            const stored: StoredPreferences = { ...this.preferences(), known: SECTIONS };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
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
        return {
            collapsed: parseCollapsed(fields['collapsed'], fields['known']) ?? fallback.collapsed,
            order: ORDERS.find((order) => order === fields['order']) ?? fallback.order,
            isMineOnly: typeof fields['isMineOnly'] === 'boolean' ? fields['isMineOnly'] : fallback.isMineOnly,
        };
    }
}

// Known sections only, in column order; anything else in storage is ignored. A section the stored value did not know
// yet takes its default.
function parseCollapsed(collapsed: unknown, known: unknown): ChatInboxSection[] | null {
    if (!Array.isArray(collapsed)) return null;
    const knownSections: readonly unknown[] = Array.isArray(known) ? known : SECTIONS_BEFORE_KNOWN;
    return SECTIONS.filter((section) =>
        knownSections.includes(section) ? collapsed.includes(section) : DEFAULT_COLLAPSED.includes(section)
    );
}
