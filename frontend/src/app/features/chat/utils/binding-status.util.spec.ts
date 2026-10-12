import { ChatBinding } from '../models/chat.model';
import { bindingStatus } from './binding-status.util';

const binding = (overrides: Partial<ChatBinding>): ChatBinding =>
    ({ is_active: true, broken_reason: null, ...overrides }) as ChatBinding;

describe('bindingStatus', () => {
    it('is live while active, paused while not, and broken whenever the flow went missing', () => {
        expect(bindingStatus(binding({}))).toBe('live');
        expect(bindingStatus(binding({ is_active: false }))).toBe('paused');
        expect(bindingStatus(binding({ is_active: false, broken_reason: 'flow deleted' }))).toBe('broken');
        expect(bindingStatus(binding({ broken_reason: 'flow deleted' }))).toBe('broken');
    });
});
