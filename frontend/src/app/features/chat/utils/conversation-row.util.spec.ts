import {
    conversationTime,
    conversationTimeLabel,
    deskRulesOf,
    isOverdue,
    operatorName,
    senderPrefix,
    visitorAvatarText,
    visitorName,
    waitDuration,
} from './conversation-row.util';

// Local wall-clock times, so the calendar-day rules hold in any time zone the tests run in.
const at = (year: number, month: number, day: number, hours = 0, minutes = 0, seconds = 0): Date =>
    new Date(year, month - 1, day, hours, minutes, seconds);
// Monday 12 October 2026, 14:30.
const NOW = at(2026, 10, 12, 14, 30).getTime();
const iso = (date: Date): string => date.toISOString();

const anonymous = (visitorNumber: number) => ({ visitor_number: visitorNumber, chat_user_id: null });
const signed = (chatUserId: string) => ({ visitor_number: 3, chat_user_id: chatUserId });

describe('visitorName', () => {
    it('calls an anonymous visitor by the number the desk gave them', () => {
        expect(visitorName(anonymous(12))).toBe('Visitor 12');
        expect(visitorName(anonymous(1))).toBe('Visitor 1');
    });

    it('calls a signed visitor by the verified customer id, whatever their number', () => {
        expect(visitorName(signed('customer-4711'))).toBe('customer-4711');
    });
});

describe('visitorAvatarText', () => {
    it('shows the number, its last three digits once it is longer', () => {
        expect(visitorAvatarText(anonymous(7))).toBe('7');
        expect(visitorAvatarText(anonymous(123))).toBe('123');
        expect(visitorAvatarText(anonymous(4821))).toBe('821');
    });

    it("shows a signed visitor's initials", () => {
        expect(visitorAvatarText(signed('jane doe'))).toBe('JD');
        expect(visitorAvatarText(signed('customer-4711'))).toBe('CU');
    });
});

describe('operatorName', () => {
    it('is the display name, or "Operator #id" while it is not known', () => {
        expect(operatorName(7, 'Ada Lovelace')).toBe('Ada Lovelace');
        expect(operatorName(7, null)).toBe('Operator #7');
        expect(operatorName(7, '')).toBe('Operator #7');
    });
});

describe('senderPrefix', () => {
    const last = (
        role: 'user' | 'assistant' | 'operator' | 'system' | null,
        authorId: number | null = null,
        authorName: string | null = null
    ) => ({ last_message_role: role, last_message_author_user_id: authorId, last_message_author_name: authorName });

    it('says "You:" when the current user wrote last', () => {
        expect(senderPrefix(last('operator', 3, 'Ada Lovelace'), 3)).toBe('You:');
    });

    it('names another operator, or numbers them while the name is not known', () => {
        expect(senderPrefix(last('operator', 7, 'Grace Hopper'), 3)).toBe('Grace Hopper:');
        expect(senderPrefix(last('operator', 7, null), 3)).toBe('Operator #7:');
        expect(senderPrefix(last('operator', 7, 'Grace Hopper'), null)).toBe('Grace Hopper:');
    });

    it('falls back to "Operator:" for an operator reply without its author', () => {
        expect(senderPrefix(last('operator'), 3)).toBe('Operator:');
    });

    it('says "Bot:" for the bot', () => {
        expect(senderPrefix(last('assistant'), 3)).toBe('Bot:');
    });

    it('adds nothing for the visitor, a system note or no message yet', () => {
        expect(senderPrefix(last('user'), 3)).toBeNull();
        expect(senderPrefix(last('system'), 3)).toBeNull();
        expect(senderPrefix(last(null), 3)).toBeNull();
    });
});

// Angular's en-US time format may put a narrow no-break space before AM/PM.
const plain = (text: string): string => text.replace(/\s/g, ' ');
const LOCALE = 'en-US';

describe('conversationTime', () => {
    it.each([
        ['under a minute ago', at(2026, 10, 12, 14, 29, 31), 'now'],
        ['a time ahead of now (clock skew)', at(2026, 10, 12, 14, 31), 'now'],
        ['one minute ago', at(2026, 10, 12, 14, 29), '1m'],
        ['under an hour ago', at(2026, 10, 12, 13, 31), '59m'],
        ['earlier today, as the locale writes the clock', at(2026, 10, 12, 9, 5), '9:05 AM'],
        ['just after midnight today', at(2026, 10, 12, 0, 1), '12:01 AM'],
        ['yesterday', at(2026, 10, 11, 23, 0), 'Yesterday'],
        ['within the week', at(2026, 10, 7, 10, 0), 'Wed'],
        ['six days ago', at(2026, 10, 6, 10, 0), 'Tue'],
        ['a week ago or more', at(2026, 10, 5, 10, 0), 'Oct 5'],
        ['an earlier year', at(2025, 12, 31, 10, 0), 'Dec 31, 2025'],
    ])('shows %s as %s', (_case, date, expected) => {
        expect(plain(conversationTime(iso(date), NOW, LOCALE))).toBe(expected);
    });

    it('counts minutes, not the calendar, within the hour across midnight', () => {
        const justAfterMidnight = at(2026, 10, 13, 0, 10).getTime();
        expect(conversationTime(iso(at(2026, 10, 12, 23, 50)), justAfterMidnight, LOCALE)).toBe('20m');
        expect(conversationTime(iso(at(2026, 10, 12, 22, 0)), justAfterMidnight, LOCALE)).toBe('Yesterday');
    });

    it('follows the locale for the clock and the date', () => {
        expect(plain(conversationTime(iso(at(2026, 10, 12, 14, 5)), at(2026, 10, 12, 18, 0).getTime(), LOCALE))).toBe(
            '2:05 PM'
        );
    });

    it('is empty for a conversation without messages', () => {
        expect(conversationTime(null, NOW, LOCALE)).toBe('');
        expect(conversationTimeLabel(null, NOW, LOCALE)).toBe('');
    });
});

describe('conversationTimeLabel', () => {
    it.each([
        [at(2026, 10, 12, 14, 29, 40), 'today at 2:29 PM'],
        [at(2026, 10, 12, 9, 5), 'today at 9:05 AM'],
        [at(2026, 10, 11, 9, 5), 'yesterday at 9:05 AM'],
        [at(2026, 10, 7, 16, 30), 'Wednesday at 4:30 PM'],
        [at(2026, 10, 5, 9, 5), 'October 5'],
        [at(2025, 12, 31, 9, 5), 'December 31, 2025'],
    ])('says %s in words', (date, expected) => {
        expect(plain(conversationTimeLabel(iso(date), NOW, LOCALE))).toBe(expected);
    });

    it('stays the same as the clock ticks within the day, unlike the relative time', () => {
        const sent = iso(at(2026, 10, 12, 14, 24));
        const later = at(2026, 10, 12, 14, 52).getTime();
        expect(conversationTimeLabel(sent, later, LOCALE)).toBe(conversationTimeLabel(sent, NOW, LOCALE));
        expect(conversationTime(sent, later, LOCALE)).not.toBe(conversationTime(sent, NOW, LOCALE));
    });
});

describe('waitDuration', () => {
    it.each([
        [at(2026, 10, 12, 14, 29, 30), '<1m'],
        [at(2026, 10, 12, 14, 26), '4m'],
        [at(2026, 10, 12, 13, 25), '1h 5m'],
        [at(2026, 10, 12, 11, 30), '3h'],
        [at(2026, 10, 10, 13, 0), '2d'],
        // Clock skew: never a negative wait.
        [at(2026, 10, 12, 14, 35), '<1m'],
    ])('waited since %s: %s', (since, expected) => {
        expect(waitDuration(iso(since), NOW)).toBe(expected);
    });

    it('is empty without a usable time, never "NaNd"', () => {
        expect(waitDuration(null, NOW)).toBe('');
        expect(waitDuration(undefined, NOW)).toBe('');
        expect(waitDuration('not a time', NOW)).toBe('');
    });
});

describe('isOverdue', () => {
    const tenMinutes = 10 * 60_000;
    const since = iso(at(2026, 10, 12, 14, 20));

    it('marks a wait past the response time, not one that has just reached it', () => {
        expect(isOverdue(since, tenMinutes, NOW - 1)).toBe(false);
        expect(isOverdue(since, tenMinutes, NOW)).toBe(false);
        expect(isOverdue(since, tenMinutes, NOW + 1)).toBe(true);
    });

    it('marks nothing on a desk that does not mark overdue, nor without a usable wait', () => {
        expect(isOverdue(since, null, NOW + 60 * 60_000)).toBe(false);
        expect(isOverdue(null, tenMinutes, NOW)).toBe(false);
        expect(isOverdue(undefined, tenMinutes, NOW)).toBe(false);
        expect(isOverdue('not a time', tenMinutes, NOW)).toBe(false);
    });
});

describe('deskRulesOf', () => {
    it('turns a wait overdue after the response time only on a desk whose rule is to mark it', () => {
        const desk = { style: 'support', response_time_seconds: 600 } as const;
        expect(deskRulesOf({ ...desk, on_response_timeout: 'overdue' })).toEqual({
            style: 'support',
            overdueAfterMs: 600_000,
        });
        expect(deskRulesOf({ ...desk, on_response_timeout: 'handback' }).overdueAfterMs).toBeNull();
        expect(deskRulesOf({ ...desk, style: 'ongoing', on_response_timeout: 'wait' })).toEqual({
            style: 'ongoing',
            overdueAfterMs: null,
        });
    });
});
