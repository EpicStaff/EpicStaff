import { PERSISTENCE_MODE_VISUALS, persistenceSubtitle } from './persistence-mode-visuals';

describe('persistence mode visuals', () => {
    it('gives every mode an icon, a word and an accent token', () => {
        for (const mode of ['read', 'write', 'delete'] as const) {
            const visual = PERSISTENCE_MODE_VISUALS[mode];
            expect(visual.icon).toMatch(/^ti ti-/);
            expect(visual.label.length).toBeGreaterThan(0);
            expect(visual.accentVar).toMatch(/^--/);
        }
    });

    it('formats the subtitle', () => {
        expect(persistenceSubtitle('write', 'customers', 3)).toBe('Write · customers · 3 keys');
        expect(persistenceSubtitle('read', 'customers', 1)).toBe('Read · customers · 1 key');
        expect(persistenceSubtitle('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });
});
