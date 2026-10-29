import { diffProjections } from './diff-fields';
import { Projection } from './semantic-projections';

function keyed(items: Record<string, Projection>): Record<string, Projection> {
    return Object.assign(Object.create(null) as Record<string, Projection>, items);
}

describe('diffProjections', () => {
    it.each([
        [
            'an item in the version only is added by a restore',
            { condition_groups: keyed({}) },
            { condition_groups: keyed({ yes: { position: 1 } }) },
            { path: 'condition_groups[name=yes]', status: 'added', current: null, version: { position: 1 } },
        ],
        [
            'an item on the canvas only is deleted by a restore',
            { condition_groups: keyed({ yes: { position: 1 } }) },
            { condition_groups: keyed({}) },
            { path: 'condition_groups[name=yes]', status: 'deleted', current: { position: 1 }, version: null },
        ],
        [
            'a nested field in the version only is added by a restore',
            { python_code: null },
            { python_code: { code: 'x' } },
            { path: 'python_code', status: 'added', current: null, version: { code: 'x' } },
        ],
        [
            'a changed field reads current → version',
            { node_name: 'Now' },
            { node_name: 'Then' },
            { path: 'node_name', status: 'changed', current: 'Now', version: 'Then' },
        ],
    ])('%s', (_case, current, version, expected) => {
        expect(diffProjections(current, version)).toEqual([expect.objectContaining(expected)]);
    });

    it.each([
        ['a nested field', { python_code: 'old code' }, { python_code: 'new code' }, 'python_code'],
        [
            'a nested field that is an object on one side only',
            { python_code: 'old' },
            { python_code: { code: 'x' } },
            'python_code',
        ],
        ['a keyed collection', { condition_groups: ['yes'] }, { condition_groups: ['no'] }, 'condition_groups'],
        [
            'a keyed item',
            { condition_groups: keyed({ yes: { position: 1 } }) },
            { condition_groups: keyed({ yes: 'broken' as unknown as Projection }) },
            'condition_groups[name=yes]',
        ],
    ])(
        'compares %s whole when a value is not an object, so the difference is not hidden',
        (_case, current, version, path) => {
            expect(diffProjections(current, version).map((change) => [change.path, change.status])).toEqual([
                [path, 'changed'],
            ]);
        }
    );
});
