import {
    areValidParameterNames,
    diffNames,
    NameChanges,
    parseMainParameters,
    planInputListChanges,
    rewriteMainParameters,
} from './python-main-signature.util';

const NO_CHANGES: NameChanges = { renamed: [], added: [], removed: [] };

function changes(partial: Partial<NameChanges>): NameChanges {
    return { ...NO_CHANGES, ...partial };
}

describe('parseMainParameters', () => {
    it.each([
        ['no parameters', 'def main():\n    return\n', []],
        ['plain parameters', 'def main(a, b):\n    return a', ['a', 'b']],
        [
            'a signature over several lines with a trailing comma and comments',
            'def main(\n    first: int,  # the count\n    second,\n) -> dict:\n    return {}',
            ['first', 'second'],
        ],
        [
            'type hints and defaults holding brackets, commas and strings',
            'def main(x: dict = {"a": (1, 2)}, y: list[tuple[int, str]] = [], z: str = "a, b)", w="""(""") -> None:',
            ['x', 'y', 'z', 'w'],
        ],
        ['*args, **kwargs, bare * and /', 'def main(a, /, b, *args, c, **kwargs):\n    pass', ['a', 'b', 'c']],
        ['keyword-only parameters after a bare *', 'def main(*, token: str):', ['token']],
        [
            'the top-level main only, not a nested one or a comment',
            '# def main(commented)\ndef helper():\n    def main(inner):\n        pass\n\ndef main(outer):\n    pass',
            ['outer'],
        ],
    ])('reads %s', (_case, code, expected) => {
        expect(parseMainParameters(code)?.names).toEqual(expected);
    });

    it.each([
        ['def main(a, **kwargs):', true],
        ['def main(a, *args):', false],
        ['def main(a, b):', false],
    ])('tells whether %s takes any keyword', (code, expected) => {
        expect(parseMainParameters(code)?.acceptsAnyKeyword).toBe(expected);
    });

    it.each([
        ['code without a main()', 'def handler(a):\n    pass'],
        ['an unclosed parameter list (still being typed)', 'def main(a, b: dict = {"x": 1'],
        ['an unclosed string in a default', 'def main(a="x, b):'],
        ['an empty entry between commas', 'def main(a, , b):'],
        ['a parameter that is not a name yet', 'def main(a-b):'],
        ['mismatched brackets', 'def main(a: list[int):'],
        ['a repeated name', 'def main(a, b, a):'],
    ])('returns null for %s', (_case, code) => {
        expect(parseMainParameters(code)).toBeNull();
    });
});

describe('areValidParameterNames', () => {
    it.each([
        [['count', '_private', 'größe'], true],
        [['a-b'], false],
        [['1a'], false],
        [['class'], false],
        [['in'], false],
        [['None'], false],
        [['match', 'type'], true],
        [['a', 'a'], false],
    ])('%j is %s', (names, expected) => {
        expect(areValidParameterNames(names)).toBe(expected);
    });
});

describe('diffNames', () => {
    it.each([
        ['nothing for a reorder', ['a', 'b'], ['b', 'a'], NO_CHANGES],
        ['a rename in place', ['a', 'b'], ['a', 'c'], changes({ renamed: [{ from: 'b', to: 'c' }] })],
        ['a removal from the middle', ['a', 'b', 'c'], ['a', 'c'], changes({ removed: ['b'] })],
        ['an addition anywhere', ['a', 'b'], ['c', 'b', 'a'], changes({ added: ['c'] })],
        [
            'renames paired in order, then the rest added',
            ['a', 'b'],
            ['x', 'y', 'z'],
            changes({
                renamed: [
                    { from: 'a', to: 'x' },
                    { from: 'b', to: 'y' },
                ],
                added: ['z'],
            }),
        ],
    ])('finds %s', (_case, previous, next, expected) => {
        expect(diffNames(previous, next)).toEqual(expected);
    });
});

describe('planInputListChanges', () => {
    it('renames and removes rows as the signature did', () => {
        expect(planInputListChanges(['a', 'b', 'c'], { names: ['x', 'c'], acceptsAnyKeyword: false })).toEqual(
            changes({ renamed: [{ from: 'a', to: 'x' }], removed: ['b'] })
        );
    });

    it('leaves the rows alone when the parameters were only reordered', () => {
        expect(planInputListChanges(['a', 'b'], { names: ['b', 'a'], acceptsAnyKeyword: false })).toEqual(NO_CHANGES);
    });

    it('only adds rows when **kwargs takes any row', () => {
        expect(planInputListChanges(['a', 'b'], { names: ['x'], acceptsAnyKeyword: true })).toEqual(
            changes({ added: ['x'] })
        );
    });

    it('only adds rows when no signature was seen before', () => {
        expect(planInputListChanges(null, { names: ['a', 'b'], acceptsAnyKeyword: false })).toEqual(
            changes({ added: ['a', 'b'] })
        );
    });
});

describe('rewriteMainParameters', () => {
    it.each([
        [
            'renames a parameter, keeping its type hint and default',
            'def main(name, count: int = 3):\n    return count',
            changes({ renamed: [{ from: 'count', to: 'total' }] }),
            'def main(name, total: int = 3):\n    return count',
        ],
        [
            'removes a middle parameter with its hint and default and one comma',
            'def main(a, b: dict = {"k": (1, 2)}, c=1):\n    return b',
            changes({ removed: ['b'] }),
            'def main(a, c=1):\n    return b',
        ],
        ['removes the first parameter', 'def main(a, b):', changes({ removed: ['a'] }), 'def main(b):'],
        ['removes the last parameter', 'def main(a, b: str = "x"):', changes({ removed: ['b'] }), 'def main(a):'],
        ['removes the only parameter', 'def main(a: int = 1):', changes({ removed: ['a'] }), 'def main():'],
        [
            'removes a parameter from a one-per-line signature',
            'def main(\n    a: int,\n    b: str,\n    c,\n):',
            changes({ removed: ['b'] }),
            'def main(\n    a: int,\n    c,\n):',
        ],
        [
            'removes the last parameter of a one-per-line signature, keeping the trailing comma',
            'def main(\n    a,\n    b,\n):',
            changes({ removed: ['b'] }),
            'def main(\n    a,\n):',
        ],
        [
            'adds a parameter to an empty signature',
            'def main():\n    return\n',
            changes({ added: ['a'] }),
            'def main(a):\n    return\n',
        ],
        ['appends a parameter', 'def main(a: int) -> int:', changes({ added: ['b'] }), 'def main(a: int, b) -> int:'],
        [
            'adds a parameter before *args and **kwargs',
            'def main(a, *args, **kwargs):',
            changes({ added: ['b'] }),
            'def main(a, b, *args, **kwargs):',
        ],
        [
            'adds a parameter before **kwargs only',
            'def main(**kwargs):',
            changes({ added: ['a'] }),
            'def main(a, **kwargs):',
        ],
        [
            'adds a keyword-only parameter after a defaulted one',
            'def main(a=1, *, b):',
            changes({ added: ['c'] }),
            'def main(a=1, *, b, c):',
        ],
        [
            'adds a parameter in a one-per-line signature on its own line',
            'def main(\n    a,\n):',
            changes({ added: ['b'] }),
            'def main(\n    a,\n    b,\n):',
        ],
        [
            'never reorders the parameters, whatever the order of the rows',
            'def main(a: int, b: str = "x"):',
            changes({ renamed: [{ from: 'b', to: 'c' }] }),
            'def main(a: int, c: str = "x"):',
        ],
        [
            'leaves *args, **kwargs, bare * and / in place',
            'def main(a, /, b, *, c, **kwargs):',
            changes({ renamed: [{ from: 'a', to: 'x' }] }),
            'def main(x, /, b, *, c, **kwargs):',
        ],
    ])('%s', (_case, code, nameChanges, expected) => {
        expect(rewriteMainParameters(code, nameChanges)).toBe(expected);
    });

    it('never touches the body, other functions or other uses of the name', () => {
        const code =
            'def helper(count):\n    return count\n\n' +
            'def main(count: int = 1):\n    """Uses count."""\n    count = helper(count)\n    return {"count": count}\n';

        expect(rewriteMainParameters(code, changes({ renamed: [{ from: 'count', to: 'total' }] }))).toBe(
            'def helper(count):\n    return count\n\n' +
                'def main(total: int = 1):\n    """Uses count."""\n    count = helper(count)\n    return {"count": count}\n'
        );
    });

    it.each([
        ['a parameter without a default after a defaulted one', 'def main(a, b="x"):', changes({ added: ['c'] })],
        ['a bare * with nothing after it', 'def main(a, *, b):', changes({ removed: ['b'] })],
        ['a / with nothing before it', 'def main(a, /, b):', changes({ removed: ['a'] })],
        ['a rename onto another parameter', 'def main(a, b):', changes({ renamed: [{ from: 'a', to: 'b' }] })],
        ['a parameter that is not there', 'def main(a, *args):', changes({ removed: ['b'] })],
        [
            'a rename of a parameter that is not there',
            'def main(**kwargs):',
            changes({ renamed: [{ from: 'b', to: 'c' }] }),
        ],
    ])('leaves the code as it is rather than write %s', (_case, code, nameChanges) => {
        expect(rewriteMainParameters(code, nameChanges)).toBe(code);
    });

    it('applies the changes that keep the code valid and skips the rest', () => {
        expect(
            rewriteMainParameters(
                'def main(a, b="x"):',
                changes({ renamed: [{ from: 'a', to: 'first' }], added: ['c'] })
            )
        ).toBe('def main(first, b="x"):');
    });

    it.each([
        ['there is no main()', '# no function yet\n', changes({ added: ['a'] })],
        ['the signature is still being typed', 'def main(a, b: dict = {', changes({ added: ['c'] })],
        ['a new name is not an identifier yet', 'def main(a):', changes({ renamed: [{ from: 'a', to: 'a-b' }] })],
        ['a new name is a Python keyword', 'def main(a):', changes({ added: ['class'] })],
    ])('returns null when %s', (_case, code, nameChanges) => {
        expect(rewriteMainParameters(code, nameChanges)).toBeNull();
    });
});
