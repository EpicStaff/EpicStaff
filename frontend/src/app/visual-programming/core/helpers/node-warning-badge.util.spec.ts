import { buildNodeWarningChip } from './node-warning-badge.util';

describe('buildNodeWarningChip', () => {
    it('counts the messages and lists each on its own bulleted line', () => {
        const chip = buildNodeWarningChip(['No LLM selected', 'Select a table in the node panel']);

        expect(chip.label).toBe('2 issues');
        expect(chip.tooltip).toBe('• No LLM selected\n• Select a table in the node panel');
    });
});
