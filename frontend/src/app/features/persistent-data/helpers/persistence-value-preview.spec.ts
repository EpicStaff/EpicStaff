import { copyableValue, previewValue } from './persistence-value-preview';

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

describe('copyableValue', () => {
    it('copies a string as its raw text', () => {
        expect(copyableValue('line "one"\nline two')).toBe('line "one"\nline two');
    });

    it('copies anything else as JSON indented by two spaces', () => {
        expect(copyableValue({ plan: 'pro', tags: [1] })).toBe('{\n  "plan": "pro",\n  "tags": [\n    1\n  ]\n}');
        expect(copyableValue(42)).toBe('42');
        expect(copyableValue(null)).toBe('null');
    });
});
