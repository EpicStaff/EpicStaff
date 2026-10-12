import { CHAT_BINDING_DEFAULTS, ChatBinding, ChatBindingInput } from '../models/chat.model';
import { bindingPatch } from './binding-patch.util';

const original: ChatBinding = {
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Support',
    bot_display_name: 'Support',
    public_key: 'pk',
    is_active: true,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
    ...CHAT_BINDING_DEFAULTS,
    allowed_origins: ['https://a.example'],
    token_budget_per_conversation: 5000,
    daily_token_budget: 1_000_000,
};

const values = (overrides: Partial<ChatBindingInput>): ChatBindingInput => ({
    name: original.name,
    bot_display_name: original.bot_display_name,
    graph_id: original.graph_id,
    ...CHAT_BINDING_DEFAULTS,
    allowed_origins: ['https://a.example'],
    token_budget_per_conversation: 5000,
    daily_token_budget: 1_000_000,
    ...overrides,
});

describe('bindingPatch', () => {
    it('is empty when nothing changed, including equal arrays', () => {
        expect(bindingPatch(original, values({}))).toEqual({});
    });

    it('contains only the changed keys', () => {
        expect(bindingPatch(original, values({ name: 'Sales', operator_display_name: 'Help desk' }))).toEqual({
            name: 'Sales',
            operator_display_name: 'Help desk',
        });
    });

    it('sends a changed budget and a new array when origins change', () => {
        expect(bindingPatch(original, values({ token_budget_per_conversation: 8000, allowed_origins: [] }))).toEqual({
            token_budget_per_conversation: 8000,
            allowed_origins: [],
        });
    });
});
