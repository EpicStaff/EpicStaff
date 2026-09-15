import { describe, expect, it } from 'vitest';

import { JsonViewerComponent } from './json-viewer.component';

function build(json: unknown, expanded = true): JsonViewerComponent {
    const component = new JsonViewerComponent();
    component.json = json;
    component.expanded = expanded;
    component.ngOnChanges();
    return component;
}

describe('JsonViewerComponent', () => {
    it('describes each primitive with its own type and rendering', () => {
        const segments = build({
            text: 'hello',
            count: 42,
            flag: false,
            missing: null,
            absent: undefined,
        }).segments;

        expect(segments.map((s) => [s.key, s.type, s.description])).toEqual([
            ['text', 'string', '"hello"'],
            ['count', 'number', '42'],
            ['flag', 'boolean', 'false'],
            ['missing', 'null', 'null'],
            ['absent', 'undefined', 'undefined'],
        ]);
    });

    it('wraps a bare primitive in a segment keyed by its type', () => {
        expect(build('just a string').segments).toEqual([
            expect.objectContaining({ key: '(string)', type: 'string', description: '"just a string"' }),
        ]);
    });

    it('replaces a cyclic reference with a $ref marker instead of recursing', () => {
        const node: Record<string, unknown> = { name: 'root' };
        node['self'] = node;

        const selfSegment = build(node).segments.find((s) => s.key === 'self');

        expect(selfSegment?.value).toEqual({ $ref: '$' });
    });

    it('only toggles segments that can expand', () => {
        const component = build({ nested: { a: 1 }, plain: 'text' });
        const [nested, plain] = component.segments;

        component.toggle(nested);
        expect(nested.expanded).toBe(false);

        component.toggle(plain);
        expect(plain.expanded).toBe(true);
    });

    it('starts every segment collapsed when expanded is false', () => {
        const segments = build({ nested: { a: 1 }, other: { b: 2 } }, false).segments;

        expect(segments.every((s) => !s.expanded)).toBe(true);
    });
});
