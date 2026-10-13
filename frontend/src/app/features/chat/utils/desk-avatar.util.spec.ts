import {
    DESK_AVATAR_COLORS,
    deskAccessibleName,
    deskAvatarColor,
    deskBadgeText,
    deskInitials,
} from './desk-avatar.util';

describe('deskInitials', () => {
    it.each([
        ['Sales', 'SA'],
        ['sales eu', 'SE'],
        ['Mary Jane Watson', 'MJ'],
        ['  Sales    EU  ', 'SE'],
        ['x', 'X'],
        ['Support 2', 'S2'],
        ['24/7 support', '2S'],
        ["Ivan's desk", 'ID'],
    ])('takes the first letters of the first two words: %s is %s', (name, initials) => {
        expect(deskInitials(name)).toBe(initials);
    });

    it('skips punctuation and emoji inside the words', () => {
        expect(deskInitials('Q&A')).toBe('QA');
        expect(deskInitials('(Beta) Sales')).toBe('BS');
        expect(deskInitials('🤖 Bot')).toBe('BO');
        expect(deskInitials('🤖 Sales bot')).toBe('SB');
    });

    it('keeps letters outside Latin and a letter with its combining accent whole', () => {
        expect(deskInitials('підтримка клієнтів')).toBe('ПК');
        expect(deskInitials('日本語サポート')).toBe('日本');
        expect(deskInitials('Éva Nagy')).toBe('ÉN');
    });

    it('shows the first symbol of a name without letters or digits, keeping an emoji sequence whole', () => {
        expect(deskInitials('🚀')).toBe('🚀');
        expect(deskInitials('👩‍💻 🚀')).toBe('👩‍💻');
        expect(deskInitials('🇺🇦')).toBe('🇺🇦');
        expect(deskInitials('---')).toBe('-');
    });

    it('is empty for a blank name, so the avatar falls back to an icon', () => {
        expect(deskInitials('')).toBe('');
        expect(deskInitials('   ')).toBe('');
    });
});

describe('deskAvatarColor', () => {
    it('picks one of the palette tokens, the same one every time for the same id', () => {
        const color = deskAvatarColor('6f1c2a9e-0d4b-4c43-9a51-2b7e8f3c1d10');
        expect(DESK_AVATAR_COLORS.map((token) => `var(${token})`)).toContain(color);
        expect(deskAvatarColor('6f1c2a9e-0d4b-4c43-9a51-2b7e8f3c1d10')).toBe(color);
    });

    it('depends on the id only, so ids one character apart can differ', () => {
        expect(deskAvatarColor('6f1c2a9e-0d4b-4c43-9a51-2b7e8f3c1d10')).not.toBe(
            deskAvatarColor('6f1c2a9e-0d4b-4c43-9a51-2b7e8f3c1d11')
        );
    });

    it('spreads ids over the whole palette', () => {
        const used = new Set(Array.from({ length: 60 }, (_, index) => deskAvatarColor(`desk-${index}`)));
        expect(used.size).toBe(DESK_AVATAR_COLORS.length);
    });
});

describe('deskBadgeText', () => {
    it('is hidden at zero, the count up to 99 and 99+ above', () => {
        expect(deskBadgeText(0)).toBeNull();
        expect(deskBadgeText(-1)).toBeNull();
        expect(deskBadgeText(1)).toBe('1');
        expect(deskBadgeText(99)).toBe('99');
        expect(deskBadgeText(100)).toBe('99+');
    });
});

describe('deskAccessibleName', () => {
    it('names the desk, its status and the exact count in words', () => {
        expect(deskAccessibleName('Sales', 'live', 2)).toBe('Sales desk, Live, 2 waiting for a person');
        expect(deskAccessibleName('Sales', 'broken', 150)).toBe('Sales desk, Broken, 150 waiting for a person');
    });

    it('leaves out a missing status and a zero count', () => {
        expect(deskAccessibleName('Sales', 'paused', 0)).toBe('Sales desk, Paused');
        expect(deskAccessibleName('All desks', null, 3)).toBe('All desks, 3 waiting for a person');
    });

    it('does not double "desk", also when it ends a longer word, and still names a blank desk', () => {
        expect(deskAccessibleName('Support Desk', 'live', 0)).toBe('Support Desk, Live');
        expect(deskAccessibleName('Helpdesk', 'live', 0)).toBe('Helpdesk, Live');
        expect(deskAccessibleName('Service-desk', 'paused', 0)).toBe('Service-desk, Paused');
        expect(deskAccessibleName('Front Desks', null, 0)).toBe('Front Desks');
        expect(deskAccessibleName('Desktop support', 'live', 0)).toBe('Desktop support desk, Live');
        expect(deskAccessibleName('  ', 'live', 0)).toBe('Desk, Live');
    });
});
