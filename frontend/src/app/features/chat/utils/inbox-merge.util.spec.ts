import { ChatConversation, ChatOperatorMessage } from '../models/chat.model';
import { INBOX_ORDER, inboxSection, microseconds, placeRow, upsertMessage } from './inbox-merge.util';

const row = (overrides: Partial<ChatConversation>): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    mode: 'bot',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: null,
    last_message_preview: '',
    handoff_reason: '',
    handoff_at: null,
    ...overrides,
});

const message = (overrides: Partial<ChatOperatorMessage>): ChatOperatorMessage => ({
    id: 'm-1',
    role: 'user',
    content: 'hi',
    actions: null,
    action: null,
    session_id: null,
    created_at: '2026-10-10T10:00:00Z',
    author_user_id: null,
    ...overrides,
});

const ids = (list: ChatConversation[]): string[] => list.map((item) => item.id);
const human = (id: string, handoffAt: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row({ id, mode: 'awaiting_human', handoff_at: handoffAt, last_message_at: handoffAt, ...overrides });
const bot = (id: string, lastMessageAt: string): ChatConversation => row({ id, last_message_at: lastMessageAt });

describe('inboxSection', () => {
    it('lists bot conversations under bot and every other mode under human', () => {
        expect(inboxSection(row({ mode: 'bot' }))).toBe('bot');
        expect(inboxSection(row({ mode: 'awaiting_human' }))).toBe('human');
        expect(inboxSection(row({ mode: 'human' }))).toBe('human');
    });

    it('lists a test conversation only under test, whatever its mode', () => {
        for (const mode of ['bot', 'awaiting_human', 'human'] as const) {
            expect(inboxSection(row({ mode, is_test: true }))).toBe('test');
        }
    });
});

describe('INBOX_ORDER', () => {
    it('orders the human section first come first served, then by id', () => {
        const sorted = [
            human('c', '2026-10-10T10:00:00Z'),
            human('b', '2026-10-10T09:00:00Z'),
            human('a', '2026-10-10T10:00:00Z'),
        ].sort(INBOX_ORDER.human);
        expect(ids(sorted)).toEqual(['b', 'a', 'c']);
    });

    it('orders the bot section newest activity first, then by id descending', () => {
        const sorted = [
            bot('a', '2026-10-10T10:00:00Z'),
            bot('b', '2026-10-10T09:00:00Z'),
            bot('c', '2026-10-10T10:00:00Z'),
        ].sort(INBOX_ORDER.bot);
        expect(ids(sorted)).toEqual(['c', 'a', 'b']);
    });

    it('orders the test section like bot: newest activity first, then by id descending', () => {
        const sorted = [
            bot('a', '2026-10-10T10:00:00Z'),
            bot('b', '2026-10-10T09:00:00Z'),
            bot('c', '2026-10-10T10:00:00Z'),
        ].sort(INBOX_ORDER.test);
        expect(ids(sorted)).toEqual(['c', 'a', 'b']);
    });
});

describe('microseconds', () => {
    it('keeps the microsecond fraction that Date drops, for Z and +00:00 alike', () => {
        expect(microseconds('2026-10-10T10:00:00.123457Z') - microseconds('2026-10-10T10:00:00.123456+00:00')).toBe(1);
        expect(microseconds('2026-10-10T10:00:00.5Z')).toBe(microseconds('2026-10-10T10:00:00.500000+00:00'));
        expect(microseconds('2026-10-10T10:00:01Z') - microseconds('2026-10-10T10:00:00.999999Z')).toBe(1);
        expect(microseconds(null)).toBe(0);
    });

    it('orders same-millisecond rows by microsecond as the server does', () => {
        const sorted = [human('a', '2026-10-10T10:00:00.123456+00:00'), human('b', '2026-10-10T10:00:00.123400Z')].sort(
            INBOX_ORDER.human
        );
        expect(ids(sorted)).toEqual(['b', 'a']);
        const newestFirst = [bot('a', '2026-10-10T10:00:00.123400Z'), bot('b', '2026-10-10T10:00:00.123456+00:00')];
        expect(ids(newestFirst.sort(INBOX_ORDER.bot))).toEqual(['b', 'a']);
    });
});

describe('placeRow', () => {
    const queue = [human('a', '2026-10-10T08:00:00Z'), human('b', '2026-10-10T09:00:00Z')];

    it('inserts a row inside the fetched window in order', () => {
        const next = placeRow(queue, human('x', '2026-10-10T08:30:00Z'), INBOX_ORDER.human, queue[1]);
        expect(ids(next)).toEqual(['a', 'x', 'b']);
    });

    it('drops a row that sorts past the boundary: it belongs to a page not fetched yet', () => {
        const next = placeRow(queue, human('x', '2026-10-10T11:00:00Z'), INBOX_ORDER.human, queue[1]);
        expect(ids(next)).toEqual(['a', 'b']);
    });

    it('places a row anywhere once every page is fetched, so a fresh handoff joins the end of the queue', () => {
        const next = placeRow(queue, human('x', '2026-10-10T11:00:00Z'), INBOX_ORDER.human, null);
        expect(ids(next)).toEqual(['a', 'b', 'x']);
    });

    it('keeps a human row where it is when newer activity arrives on it', () => {
        const replied = human('a', '2026-10-10T08:00:00Z', { mode: 'human', last_message_at: '2026-10-10T12:00:00Z' });
        const next = placeRow(queue, replied, INBOX_ORDER.human, null);
        expect(ids(next)).toEqual(['a', 'b']);
        expect(next[0].mode).toBe('human');
    });
});

describe('upsertMessage', () => {
    it('keeps the action reply of a user message when the same message arrives again', () => {
        const withAction = message({ content: '', action: { id: 'yes' } });
        expect(upsertMessage(upsertMessage([], withAction), { ...withAction })).toEqual([withAction]);
    });

    it('appends a new message in time order', () => {
        const next = upsertMessage(
            [message({ id: 'm-2', created_at: '2026-10-10T10:05:00Z' })],
            message({ id: 'm-1' })
        );
        expect(next.map((item) => item.id)).toEqual(['m-1', 'm-2']);
    });

    it('keeps one row per id and the richer operator fields whichever arrives first', () => {
        const streamed = message({ id: 'm-9', role: 'operator', created_at: '2026-10-10T10:09:00Z' });
        const fromPost = { ...streamed, session_id: 7, author_user_id: 3 };
        expect(upsertMessage(upsertMessage([], streamed), fromPost)).toEqual([fromPost]);
        expect(upsertMessage(upsertMessage([], fromPost), streamed)).toEqual([fromPost]);
    });
});
