import {
    PERSISTENCE_MODE_VISUALS,
    persistenceAccentVar,
    persistenceNodeIcon,
    persistenceSubtitle,
} from './persistence-mode-visuals';

describe('persistence mode visuals', () => {
    it('gives every mode a database icon, a word and an accent token', () => {
        for (const mode of ['read', 'write', 'delete'] as const) {
            const visual = PERSISTENCE_MODE_VISUALS[mode];
            expect(visual.icon).toMatch(/^ti ti-database-/);
            expect(visual.label.length).toBeGreaterThan(0);
            expect(visual.accentVar).toMatch(/^--/);
        }
    });

    it('formats the subtitle', () => {
        expect(persistenceSubtitle('write', 'customers', 3)).toBe('Write · customers · 3 keys');
        expect(persistenceSubtitle('read', 'customers', 1)).toBe('Read · customers · 1 key');
        expect(persistenceSubtitle('delete', null, 0)).toBe('Delete · no table · 0 keys');
    });

    it('derives the render-time icon and accent per mode, regardless of any saved node metadata', () => {
        expect(persistenceNodeIcon('read')).toBe('ti ti-database-export');
        expect(persistenceNodeIcon('write')).toBe('ti ti-database-import');
        expect(persistenceNodeIcon('delete')).toBe('ti ti-database-x');

        expect(persistenceAccentVar('read')).toBe('--color-status-info');
        expect(persistenceAccentVar('write')).toBe('--success-color');
        expect(persistenceAccentVar('delete')).toBe('--color-status-error');
    });
});
