import { describe, expect, it } from 'vitest';

import { getEntityTypeLabel, getIconForEntityType, getSpriteIcon } from './entity-icon.util';

describe('getEntityTypeLabel', () => {
    it('labels a knowledge collection by what the UI calls it, not its internal type name', () => {
        expect(getEntityTypeLabel('SourceCollection')).toBe('Knowledge Collection');
    });

    it('falls back to the type name for a type it does not know', () => {
        expect(getEntityTypeLabel('SomethingNew')).toBe('SomethingNew');
    });
});

describe('knowledge collection icon', () => {
    it('shows the knowledge icon, not the agent fallback', () => {
        expect(getSpriteIcon('SourceCollection') ?? getIconForEntityType('SourceCollection')).toBe('ui/knowledge');
    });
});
