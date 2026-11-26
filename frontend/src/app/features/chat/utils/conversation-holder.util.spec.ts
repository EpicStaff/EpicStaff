import { ChatConversation } from '../models/chat.model';
import { holderName } from './conversation-holder.util';

const MY_USER_ID = 3;

const held = (
    overrides: Partial<Pick<ChatConversation, 'assigned_operator_id' | 'assigned_operator_name' | 'status'>>
): Pick<ChatConversation, 'assigned_operator_id' | 'assigned_operator_name' | 'status'> => ({
    assigned_operator_id: null,
    assigned_operator_name: null,
    status: 'open',
    ...overrides,
});

describe('holderName', () => {
    it.each([
        { case: 'the user', overrides: { assigned_operator_id: MY_USER_ID }, name: 'you' },
        {
            case: 'a named operator',
            overrides: { assigned_operator_id: 7, assigned_operator_name: 'Grace Hopper' },
            name: 'Grace Hopper',
        },
        { case: 'an operator not named yet', overrides: { assigned_operator_id: 7 }, name: 'Operator #7' },
        { case: 'nobody', overrides: {}, name: null },
        // A close keeps the holder, but nobody is on it any more.
        {
            case: 'an operator, once closed',
            overrides: { assigned_operator_id: 7, status: 'closed' as const },
            name: null,
        },
    ])('names $case as $name', ({ overrides, name }) => {
        expect(holderName(held(overrides), MY_USER_ID)).toBe(name);
    });

    it('calls nobody "you" while the current user is not known', () => {
        expect(holderName(held({ assigned_operator_id: 7 }), null)).toBe('Operator #7');
    });
});
