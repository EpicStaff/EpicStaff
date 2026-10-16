import { ChatConversation } from '../models/chat.model';
import { closedSummary, closeReasonLabel, closeReasonWord, isClosed } from './conversation-close.util';

// Local wall-clock times, so "today" holds in any time zone the tests run in. Monday 12 October 2026, 14:30.
const NOW = new Date(2026, 9, 12, 14, 30).getTime();
const TODAY_AT_14_05 = new Date(2026, 9, 12, 14, 5).toISOString();
const OCTOBER_5_AT_9 = new Date(2026, 9, 5, 9, 0).toISOString();
// Angular's en-US time format may put a narrow no-break space before AM/PM.
const plain = (text: string): string => text.replace(/\s+/g, ' ');

type Closed = Pick<ChatConversation, 'status' | 'close_reason' | 'closed_at' | 'closed_by_user_id' | 'closed_by_name'>;
const closed = (overrides: Partial<Closed> = {}): Closed => ({
    status: 'closed',
    close_reason: 'resolved',
    closed_at: TODAY_AT_14_05,
    closed_by_user_id: 7,
    closed_by_name: 'Mike',
    ...overrides,
});

describe('isClosed', () => {
    it('reads the status, and a row without one (an older chat service) as open', () => {
        expect(isClosed({ status: 'closed' })).toBe(true);
        expect(isClosed({ status: 'open' })).toBe(false);
        expect(isClosed({} as Pick<ChatConversation, 'status'>)).toBe(false);
        expect(isClosed(null)).toBe(false);
    });
});

describe('closeReasonWord', () => {
    it("words an operator's close by the desk's style, and the others by who closed it", () => {
        expect(closeReasonWord('resolved', 'support')).toBe('Resolved');
        expect(closeReasonWord('resolved', 'ongoing')).toBe('Closed');
        expect(closeReasonWord('resolved', null)).toBe('Closed');
        expect(closeReasonWord('ended', 'support')).toBe('Ended');
        expect(closeReasonWord('inactive', 'support')).toBe('Inactive');
        expect(closeReasonWord(null, 'support')).toBe('');
    });
});

describe('closeReasonLabel', () => {
    it('names who resolved it: you, their name, or their number while the name is not known', () => {
        expect(closeReasonLabel(closed(), 'support', 3)).toBe('Resolved by Mike');
        expect(closeReasonLabel(closed({ closed_by_user_id: 3 }), 'support', 3)).toBe('Resolved by you');
        expect(closeReasonLabel(closed({ closed_by_name: null }), 'support', 3)).toBe('Resolved by Operator #7');
        expect(closeReasonLabel(closed(), 'ongoing', 3)).toBe('Closed by Mike');
    });

    it('says the visitor ended it, or that it went quiet', () => {
        expect(closeReasonLabel(closed({ close_reason: 'ended', closed_by_user_id: null }), 'support', 3)).toBe(
            'Ended by the visitor'
        );
        expect(closeReasonLabel(closed({ close_reason: 'inactive', closed_by_user_id: null }), 'support', 3)).toBe(
            'Closed after inactivity'
        );
    });
});

describe('closedSummary', () => {
    it('says Closed, why and when: the clock time today, the date before', () => {
        expect(plain(closedSummary(closed(), 'support', 3, NOW, 'en-US'))).toBe('Closed · Resolved by Mike · 2:05 PM');
        expect(
            plain(
                closedSummary(closed({ close_reason: 'ended', closed_at: OCTOBER_5_AT_9 }), 'support', 3, NOW, 'en-US')
            )
        ).toBe('Closed · Ended by the visitor · Oct 5, 9:00 AM');
    });

    it('does not say Closed twice', () => {
        expect(plain(closedSummary(closed(), 'ongoing', 3, NOW, 'en-US'))).toBe('Closed by Mike · 2:05 PM');
        expect(plain(closedSummary(closed({ close_reason: 'inactive' }), 'support', 3, NOW, 'en-US'))).toBe(
            'Closed after inactivity · 2:05 PM'
        );
    });
});
