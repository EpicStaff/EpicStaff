import { previewValue } from './persistence-value-preview';

describe('previewValue', () => {
    it('renders JSON for objects and primitives', () => {
        expect(previewValue({ a: 1 })).toBe('{"a":1}');
        expect(previewValue('text')).toBe('"text"');
        expect(previewValue(null)).toBe('null');
    });

    it('truncates long values with an ellipsis', () => {
        const preview = previewValue('x'.repeat(500), 20);
        expect(preview.length).toBe(20);
        expect(preview.endsWith('…')).toBe(true);
    });
});
