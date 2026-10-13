import { ChatConversation, ChatInboxSection, ChatOperatorMessage } from '../models/chat.model';
import { belongsTo, inboxOrder, microseconds, placeRow, upsertMessage } from './inbox-merge.util';

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
    visitor_number: 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
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
    author_name: null,
    ...overrides,
});

const ids = (list: ChatConversation[]): string[] => list.map((item) => item.id);
const waiting = (id: string, waitingSince: string, overrides: Partial<ChatConversation> = {}): ChatConversation =>
    row({
        id,
        mode: 'awaiting_human',
        handoff_at: waitingSince,
        visitor_waiting_since: waitingSince,
        last_message_at: waitingSince,
        ...overrides,
    });
const bot = (id: string, lastMessageAt: string): ChatConversation => row({ id, last_message_at: lastMessageAt });
const SECTIONS: readonly ChatInboxSection[] = ['waiting', 'in_progress', 'bot', 'test'];
const sectionsOf = (conversation: ChatConversation, holderId: number | null = null): ChatInboxSection[] =>
    SECTIONS.filter((section) => belongsTo(conversation, section, holderId));

describe('belongsTo', () => {
    const at = '2026-10-10T10:00:00Z';
    const held = { mode: 'human', assigned_operator_id: 7, handoff_at: at, last_message_at: at } as const;

    it('lists a conversation a visitor waits on under Waiting, taken or not', () => {
        expect(sectionsOf(waiting('a', at))).toEqual(['waiting']);
        expect(sectionsOf(row({ ...held, visitor_waiting_since: at }))).toEqual(['waiting']);
    });

    it('lists a taken conversation the operator answered last under In progress', () => {
        expect(sectionsOf(row(held))).toEqual(['in_progress']);
    });

    it('lists a conversation the bot runs under Bot', () => {
        expect(sectionsOf(bot('a', at))).toEqual(['bot']);
    });

    it('lists a test conversation only under Tests, whatever its mode or wait', () => {
        expect(sectionsOf(row({ is_test: true, last_message_at: at }))).toEqual(['test']);
        expect(sectionsOf(row({ ...held, is_test: true, visitor_waiting_since: at }))).toEqual(['test']);
    });

    it('lists no conversation without a message outside Waiting, as the server does', () => {
        expect(sectionsOf(row({}))).toEqual([]);
        expect(sectionsOf(row({ is_test: true }))).toEqual([]);
        expect(sectionsOf(row({ ...held, last_message_at: null }))).toEqual([]);
    });

    it('reads a missing wait field as no wait', () => {
        const legacy = row(held) as Partial<ChatConversation>;
        delete legacy.visitor_waiting_since;
        expect(sectionsOf(legacy as ChatConversation)).toEqual(['in_progress']);
    });

    it("lists only the holder's conversations for Mine, so Bot has none", () => {
        expect(sectionsOf(row(held), 7)).toEqual(['in_progress']);
        expect(sectionsOf(row(held), 8)).toEqual([]);
        expect(sectionsOf(row({ ...held, visitor_waiting_since: at }), 7)).toEqual(['waiting']);
        expect(sectionsOf(waiting('a', at), 7)).toEqual([]);
        expect(sectionsOf(bot('a', at), 7)).toEqual([]);
    });
});

describe('inboxOrder', () => {
    const latest = [
        bot('a', '2026-10-10T10:00:00Z'),
        bot('b', '2026-10-10T09:00:00Z'),
        bot('c', '2026-10-10T10:00:00Z'),
    ];

    it('orders Waiting longest wait first, then by id, in either order', () => {
        const queue = [
            waiting('c', '2026-10-10T10:00:00Z'),
            waiting('b', '2026-10-10T09:00:00Z'),
            waiting('a', '2026-10-10T10:00:00Z'),
        ];
        expect(ids([...queue].sort(inboxOrder('waiting', 'newest')))).toEqual(['b', 'a', 'c']);
        expect(ids([...queue].sort(inboxOrder('waiting', 'oldest')))).toEqual(['b', 'a', 'c']);
    });

    it('orders Waiting by when the wait started, not by the latest message', () => {
        const queue = [
            waiting('a', '2026-10-10T09:00:00Z', { last_message_at: '2026-10-10T12:00:00Z' }),
            waiting('b', '2026-10-10T10:00:00Z', { last_message_at: '2026-10-10T10:00:00Z' }),
        ];
        expect(ids(queue.sort(inboxOrder('waiting', 'newest')))).toEqual(['a', 'b']);
    });

    for (const section of ['in_progress', 'bot', 'test'] as const) {
        it(`orders ${section} newest message first, then by id descending`, () => {
            expect(ids([...latest].sort(inboxOrder(section, 'newest')))).toEqual(['c', 'a', 'b']);
        });

        it(`orders ${section} oldest message first, then by id ascending`, () => {
            expect(ids([...latest].sort(inboxOrder(section, 'oldest')))).toEqual(['b', 'a', 'c']);
        });
    }
});

describe('microseconds', () => {
    it('keeps the microsecond fraction that Date drops, for Z and +00:00 alike', () => {
        expect(microseconds('2026-10-10T10:00:00.123457Z') - microseconds('2026-10-10T10:00:00.123456+00:00')).toBe(1);
        expect(microseconds('2026-10-10T10:00:00.5Z')).toBe(microseconds('2026-10-10T10:00:00.500000+00:00'));
        expect(microseconds('2026-10-10T10:00:01Z') - microseconds('2026-10-10T10:00:00.999999Z')).toBe(1);
        expect(microseconds(null)).toBe(0);
    });

    it('orders same-millisecond rows by microsecond as the server does', () => {
        const sorted = [
            waiting('a', '2026-10-10T10:00:00.123456+00:00'),
            waiting('b', '2026-10-10T10:00:00.123400Z'),
        ].sort(inboxOrder('waiting', 'newest'));
        expect(ids(sorted)).toEqual(['b', 'a']);
        const newestFirst = [bot('a', '2026-10-10T10:00:00.123400Z'), bot('b', '2026-10-10T10:00:00.123456+00:00')];
        expect(ids(newestFirst.sort(inboxOrder('bot', 'newest')))).toEqual(['b', 'a']);
    });
});

describe('placeRow', () => {
    const queue = [waiting('a', '2026-10-10T08:00:00Z'), waiting('b', '2026-10-10T09:00:00Z')];
    const queueOrder = inboxOrder('waiting', 'newest');

    it('inserts a row inside the fetched window in order', () => {
        const next = placeRow(queue, waiting('x', '2026-10-10T08:30:00Z'), queueOrder, queue[1]);
        expect(ids(next)).toEqual(['a', 'x', 'b']);
    });

    it('drops a row that sorts past the boundary: it belongs to a page not fetched yet', () => {
        const next = placeRow(queue, waiting('x', '2026-10-10T11:00:00Z'), queueOrder, queue[1]);
        expect(ids(next)).toEqual(['a', 'b']);
    });

    it('places a row anywhere once every page is fetched, so a fresh wait joins the end of the queue', () => {
        const next = placeRow(queue, waiting('x', '2026-10-10T11:00:00Z'), queueOrder, null);
        expect(ids(next)).toEqual(['a', 'b', 'x']);
    });

    it('keeps a waiting row where it is when the visitor writes again', () => {
        const replied = waiting('a', '2026-10-10T08:00:00Z', {
            mode: 'human',
            last_message_at: '2026-10-10T12:00:00Z',
        });
        const next = placeRow(queue, replied, queueOrder, null);
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
        const fromPost = { ...streamed, session_id: 7, author_user_id: 3, author_name: 'Ada Lovelace' };
        expect(upsertMessage(upsertMessage([], streamed), fromPost)).toEqual([fromPost]);
        expect(upsertMessage(upsertMessage([], fromPost), streamed)).toEqual([fromPost]);
    });
});
