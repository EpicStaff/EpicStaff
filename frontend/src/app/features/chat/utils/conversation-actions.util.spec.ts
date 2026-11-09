import {
    ConversationActionContext,
    conversationHolder,
    conversationMenuItems,
    primaryConversationAction,
} from './conversation-actions.util';

const context = (overrides: Partial<ConversationActionContext>): ConversationActionContext => ({
    style: 'support',
    holder: 'none',
    isClosed: false,
    isPhone: false,
    canUse: true,
    isPending: false,
    ...overrides,
});

const labels = (overrides: Partial<ConversationActionContext>): { primary: string | null; menu: string[] } => ({
    primary: primaryConversationAction(context(overrides))?.label ?? null,
    menu: conversationMenuItems(context(overrides)).map(({ label }) => label),
});

describe('conversationHolder', () => {
    it("is the user's or another operator's while taken, and nobody's otherwise", () => {
        expect(conversationHolder({ mode: 'human', assigned_operator_id: 3 }, 3)).toBe('me');
        expect(conversationHolder({ mode: 'human', assigned_operator_id: 7 }, 3)).toBe('other');
        expect(conversationHolder({ mode: 'human', assigned_operator_id: 7 }, null)).toBe('other');
        expect(conversationHolder({ mode: 'awaiting_human', assigned_operator_id: null }, 3)).toBe('none');
        expect(conversationHolder({ mode: 'bot', assigned_operator_id: null }, 3)).toBe('none');
    });
});

describe('the conversation actions', () => {
    // For each desk style and holder: the main action, the desktop ⋯ menu, and the phone's menu (no button there).
    it.each([
        // Support: Resolve is the main action whoever holds the conversation, so the desktop menu never has it.
        {
            style: 'support',
            holder: 'me',
            primary: 'Resolve',
            wide: ['Hand Back to Bot'],
            phone: ['Resolve', 'Hand Back to Bot'],
        },
        {
            style: 'support',
            holder: 'other',
            primary: 'Resolve',
            wide: ['Take over', 'Hand Back to Bot'],
            phone: ['Resolve', 'Take over', 'Hand Back to Bot'],
        },
        { style: 'support', holder: 'none', primary: 'Resolve', wide: [], phone: ['Resolve'] },
        // Ongoing: only the holder has a main action (Done); Close conversation stays in the menu.
        {
            style: 'ongoing',
            holder: 'me',
            primary: 'Done',
            wide: ['Close conversation'],
            phone: ['Done', 'Close conversation'],
        },
        {
            style: 'ongoing',
            holder: 'other',
            primary: null,
            wide: ['Take over', 'Hand Back to Bot', 'Close conversation'],
            phone: ['Take over', 'Hand Back to Bot', 'Close conversation'],
        },
        {
            style: 'ongoing',
            holder: 'none',
            primary: null,
            wide: ['Close conversation'],
            phone: ['Close conversation'],
        },
        // A desk not known yet: no close at all; the holder may still release it.
        { style: null, holder: 'me', primary: 'Release', wide: [], phone: ['Release'] },
        {
            style: null,
            holder: 'other',
            primary: null,
            wide: ['Take over', 'Hand Back to Bot'],
            phone: ['Take over', 'Hand Back to Bot'],
        },
        { style: null, holder: 'none', primary: null, wide: [], phone: [] },
    ] as const)(
        'on a $style desk, held by $holder: $primary, then the menu',
        ({ style, holder, primary, wide, phone }) => {
            expect(labels({ style, holder })).toEqual({ primary, menu: wide });
            expect(labels({ style, holder, isPhone: true })).toEqual({ primary, menu: phone });
        }
    );

    it.each(['support', 'ongoing', null] as const)(
        'offers nothing on a %s desk once closed, nor without chats use',
        (style) => {
            for (const holder of ['me', 'other', 'none'] as const) {
                for (const isPhone of [false, true]) {
                    expect(labels({ style, holder, isPhone, isClosed: true })).toEqual({ primary: null, menu: [] });
                    expect(labels({ style, holder, isPhone, canUse: false })).toEqual({ primary: null, menu: [] });
                }
            }
        }
    );

    it('maps each item to its action: Done and Hand Back to Bot release, Resolve and Close conversation close', () => {
        expect(primaryConversationAction(context({ holder: 'me' }))?.id).toBe('resolve');
        expect(primaryConversationAction(context({ style: 'ongoing', holder: 'me' }))?.id).toBe('release');
        expect(conversationMenuItems(context({ style: 'ongoing', holder: 'other' })).map(({ id }) => id)).toEqual([
            'take-over',
            'release',
            'close',
        ]);
    });

    it('disables every menu item while another action runs, the main action on a phone included', () => {
        const items = conversationMenuItems(context({ holder: 'me', isPhone: true, isPending: true }));
        expect(items.map(({ disabled }) => disabled)).toEqual([true, true]);
        expect(
            conversationMenuItems(context({ holder: 'other', isPending: true })).every(({ disabled }) => disabled)
        ).toBe(true);
    });
});
