import { computed, Injectable, signal } from '@angular/core';

import { ChatInboxOrder, ChatInboxSection } from '../models/chat.model';

const STORAGE_KEY = 'chat:conversationList';
const SECTIONS: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'test', 'bot'];
const ORDERS: readonly ChatInboxOrder[] = ['newest', 'oldest'];
// Tests are there to look into, not to work through.
const DEFAULT_COLLAPSED: readonly ChatInboxSection[] = ['test'];

/** What the conversations column remembers per browser, as one JSON object. The search is never remembered. */
interface ConversationListPreferences {
    collapsed: ChatInboxSection[];
    order: ChatInboxOrder;
    // Only the conversations the user holds.
    isMineOnly: boolean;
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
    /** In progress, Tests and Bot; Waiting is always longest wait first. */
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
        return {
            collapsed: parseCollapsed(fields['collapsed']) ?? fallback.collapsed,
            order: ORDERS.find((order) => order === fields['order']) ?? fallback.order,
            isMineOnly: typeof fields['isMineOnly'] === 'boolean' ? fields['isMineOnly'] : fallback.isMineOnly,
        };
    }
}

// Known sections only, in column order; anything else in storage is ignored.
function parseCollapsed(collapsed: unknown): ChatInboxSection[] | null {
    if (!Array.isArray(collapsed)) return null;
    return SECTIONS.filter((section) => collapsed.includes(section));
}
