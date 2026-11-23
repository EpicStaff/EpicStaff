import { ChatConversation } from '../models/chat.model';
import { sectionOfConversation } from './conversation-section.util';

const MESSAGE_AT = '2026-10-12T14:24:00.000000Z';
const HANDOFF_AT = '2026-10-12T14:20:00.000000Z';

const conversation = (overrides: Partial<ChatConversation>): ChatConversation => ({
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
    claimed_at: null,
    visitor_number: 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: null,
    status: 'open',
    close_reason: null,
    closed_at: null,
    closed_by_user_id: null,
    closed_by_name: null,
    ...overrides,
});

describe('sectionOfConversation', () => {
    it.each([
        {
            case: 'handed off and waiting, before any message',
            overrides: { mode: 'awaiting_human' as const, handoff_at: HANDOFF_AT, visitor_waiting_since: HANDOFF_AT },
            section: 'waiting',
        },
        {
            case: 'taken over, with the visitor writing again',
            overrides: {
                mode: 'human' as const,
                handoff_at: HANDOFF_AT,
                visitor_waiting_since: MESSAGE_AT,
                assigned_operator_id: 7,
                last_message_at: MESSAGE_AT,
            },
            section: 'waiting',
        },
        {
            // Whoever holds it: Mine's filter is not the section's.
            case: 'taken over by another operator and answered',
            overrides: {
                mode: 'human' as const,
                handoff_at: HANDOFF_AT,
                assigned_operator_id: 7,
                last_message_at: MESSAGE_AT,
            },
            section: 'in_progress',
        },
        { case: 'with the bot', overrides: { last_message_at: MESSAGE_AT }, section: 'bot' },
        {
            case: 'closed',
            overrides: { status: 'closed' as const, closed_at: MESSAGE_AT, last_message_at: MESSAGE_AT },
            section: 'closed',
        },
        { case: 'an open test', overrides: { is_test: true, last_message_at: MESSAGE_AT }, section: 'test_open' },
        {
            case: 'a closed test',
            overrides: { is_test: true, status: 'closed' as const, last_message_at: MESSAGE_AT },
            section: 'test_closed',
        },
        {
            case: 'a waiting test, which Bot Testing keeps',
            overrides: { is_test: true, visitor_waiting_since: MESSAGE_AT, last_message_at: MESSAGE_AT },
            section: 'test_open',
        },
    ])('is $section for a conversation $case', ({ overrides, section }) => {
        expect(sectionOfConversation(conversation(overrides))).toBe(section);
    });

    // The server lists a conversation nowhere until its first message, outside Waiting: so does the column.
    it.each([
        { case: 'with the bot', overrides: {} },
        { case: 'taken over', overrides: { mode: 'human' as const, handoff_at: HANDOFF_AT, assigned_operator_id: 7 } },
        { case: 'closed', overrides: { status: 'closed' as const } },
        { case: 'a test', overrides: { is_test: true } },
    ])('is none for a conversation $case without a message yet', ({ overrides }) => {
        expect(sectionOfConversation(conversation(overrides))).toBeNull();
    });
});
