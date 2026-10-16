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
    describe.each([
        // Desk style, then for the holder on a wide screen and on a phone, another operator's and nobody's.
        {
            style: 'support',
            holderWide: { primary: 'Resolve', menu: ['Release to bot'] },
            holderPhone: ['Resolve', 'Release to bot'],
            other: ['Take over', 'Release to bot', 'Resolve'],
            none: ['Resolve'],
        },
        {
            style: 'ongoing',
            holderWide: { primary: 'Done', menu: ['Close conversation'] },
            holderPhone: ['Done', 'Close conversation'],
            other: ['Take over', 'Release to bot', 'Close conversation'],
            none: ['Close conversation'],
        },
        {
            style: null,
            holderWide: { primary: 'Release', menu: [] },
            holderPhone: ['Release'],
            other: ['Take over', 'Release to bot'],
            none: [],
        },
    ] as const)('on a desk of style $style', ({ style, holderWide, holderPhone, other, none }) => {
        it('gives the holder the main action beside the title and the rest in the menu', () => {
            expect(labels({ style, holder: 'me' })).toEqual(holderWide);
        });

        it('leads the menu with the main action on a phone, which has no room for its button', () => {
            expect(labels({ style, holder: 'me', isPhone: true })).toEqual({
                primary: holderWide.primary,
                menu: holderPhone,
            });
        });

        it("offers Take over, Release to bot and the close on another operator's conversation", () => {
            expect(labels({ style, holder: 'other' })).toEqual({ primary: null, menu: other });
        });

        it("offers the close only on an unclaimed or the bot's conversation", () => {
            expect(labels({ style, holder: 'none' })).toEqual({ primary: null, menu: none });
        });

        it('offers nothing on a closed conversation, nor without chats use', () => {
            for (const holder of ['me', 'other', 'none'] as const) {
                expect(labels({ style, holder, isClosed: true })).toEqual({ primary: null, menu: [] });
                expect(labels({ style, holder, canUse: false })).toEqual({ primary: null, menu: [] });
            }
        });
    });

    it('maps each item to its action: Done and Release to bot release, Resolve and Close conversation close', () => {
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
