/**
 * Sample data for running the app outside EpicStaff (`npm start` in a normal browser tab). Loaded
 * as a lazy chunk only when the page is not framed, so the production app never downloads it.
 *
 * The mocked `chat` flow does what the real Chat Admin flow does: reads the conversation record
 * from the key-value table, appends the turn, writes it back, and returns `{answer, conversation_id}`.
 */
import { createMockHost, type MockFlowContext, type MockHost, type MockKvEntry } from '@epicstaff/plugin-sdk/mock-host';

import { CHAT_FLOW_ALIAS, CONVERSATIONS_TABLE_ALIAS } from '../conversations/conversation.model';

const ANSWER_DELAY_MS = 700;
const MAX_RECORD_BYTES = 200_000;
const HOUR_MS = 60 * 60 * 1000;

const SAMPLE_QUESTIONS = [
    'How do I reset my password?',
    'Can I export a report to PDF?',
    'What is included in the Pro plan?',
    'How do I share a workspace with my team?',
    'Does the desktop app work offline?',
    'How do I cancel my subscription?',
    'Where can I find the API documentation?',
    'Is my data encrypted at rest?',
    'How do I import data from a spreadsheet?',
    'Can I use Markdown in comments?',
    'Why is sync slow on my phone?',
    'How many devices can I use with one account?',
    'Do you offer a discount for non-profits?',
];
const SAMPLE_CONVERSATION_COUNT = 26;

interface RecordMessage {
    role: 'user' | 'assistant';
    content: string;
    at: string;
}

interface ConversationRecord {
    title: string;
    turns: number;
    messages: RecordMessage[];
    started_at: string;
    updated_at: string;
    conversation_id: string;
}

export function createChatAdminMockHost(): MockHost {
    return createMockHost({
        plugin: { id: 'chat-admin', version: '0.1.0', name: 'Chat Admin' },
        access: [
            { alias: CHAT_FLOW_ALIAS, type: 'flow', actions: ['run', 'sessions.read', 'sessions.stop'] },
            { alias: CONVERSATIONS_TABLE_ALIAS, type: 'key_value_table', actions: ['read'] },
        ],
        flows: { [CHAT_FLOW_ALIAS]: answerLikeTheChatFlow },
        kvTables: { [CONVERSATIONS_TABLE_ALIAS]: sampleConversations(Date.now()) },
    });
}

async function answerLikeTheChatFlow(variables: Record<string, unknown>, context: MockFlowContext): Promise<unknown> {
    const conversationId = typeof variables['conversation_id'] === 'string' ? variables['conversation_id'] : '';
    const question = typeof variables['question'] === 'string' ? variables['question'].trim() : '';
    if (conversationId === '' || question === '') throw new Error('conversation_id and question are required.');

    await new Promise((resolve) => setTimeout(resolve, ANSWER_DELAY_MS));
    const answer =
        `This is a sample answer from the mock host. Inside EpicStaff, the plugin's chat flow answers ` +
        `"${question}" with its assistant and saves the turn to the conversations table.`;
    const stored = context.kv.get(CONVERSATIONS_TABLE_ALIAS, conversationId)?.value;
    const record = appendTurn(stored, conversationId, question, answer, new Date().toISOString());
    context.kv.set(CONVERSATIONS_TABLE_ALIAS, conversationId, record);
    return { answer, conversation_id: conversationId };
}

/** Appends one question and answer; drops the oldest pairs while the record is over the size cap. */
function appendTurn(
    stored: unknown,
    conversationId: string,
    question: string,
    answer: string,
    now: string
): ConversationRecord {
    const previous = isConversationRecord(stored) ? stored : null;
    const record: ConversationRecord = {
        title: previous?.title ?? question.slice(0, 80),
        turns: (previous?.turns ?? 0) + 1,
        messages: [
            ...(previous?.messages ?? []),
            { role: 'user', content: question, at: now },
            { role: 'assistant', content: answer, at: now },
        ],
        started_at: previous?.started_at ?? now,
        updated_at: now,
        conversation_id: conversationId,
    };
    while (record.messages.length > 2 && new TextEncoder().encode(JSON.stringify(record)).length > MAX_RECORD_BYTES) {
        record.messages.splice(0, 2);
    }
    return record;
}

function sampleConversations(now: number): MockKvEntry[] {
    return Array.from({ length: SAMPLE_CONVERSATION_COUNT }, (_, index) => {
        const conversationId = sampleId(index);
        const question = SAMPLE_QUESTIONS[index % SAMPLE_QUESTIONS.length] ?? 'Hello';
        const turns = (index % 3) + 1;
        const started = new Date(now - (index * 5 + turns) * HOUR_MS);
        const messages: RecordMessage[] = [];
        for (let turn = 0; turn < turns; turn++) {
            const at = new Date(started.getTime() + turn * 10 * 60 * 1000).toISOString();
            messages.push(
                { role: 'user', content: turn === 0 ? question : `Follow-up ${turn}: can you give an example?`, at },
                { role: 'assistant', content: `Sample answer ${turn + 1} to "${question}".`, at }
            );
        }
        const updatedAt = messages.at(-1)?.at ?? started.toISOString();
        const record: ConversationRecord = {
            title: question,
            turns,
            messages,
            started_at: started.toISOString(),
            updated_at: updatedAt,
            conversation_id: conversationId,
        };
        return { key: conversationId, value: record, created_at: started.toISOString(), updated_at: updatedAt };
    });
}

/** A stable id per sample row (`c_` + 24 hex), so links to sample conversations survive a reload. */
function sampleId(index: number): string {
    let hex = '';
    let seed = (index + 1) * 2654435761;
    while (hex.length < 24) {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        hex += seed.toString(16).padStart(8, '0').slice(-6);
    }
    return 'c_' + hex.slice(0, 24);
}

function isConversationRecord(value: unknown): value is ConversationRecord {
    return (
        typeof value === 'object' &&
        value !== null &&
        Array.isArray((value as Partial<ConversationRecord>).messages) &&
        typeof (value as Partial<ConversationRecord>).title === 'string'
    );
}
