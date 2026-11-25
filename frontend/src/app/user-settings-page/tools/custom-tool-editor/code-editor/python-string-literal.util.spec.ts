import { pythonStringLiteral } from './python-string-literal.util';

describe('pythonStringLiteral', () => {
    it.each([
        ['a plain name', 'plain', '"plain"'],
        ['a double quote', 'a"b', '"a\\"b"'],
        ['a backslash', 'a\\b', '"a\\\\b"'],
        ['a newline', 'a\nb', '"a\\nb"'],
        ['a carriage return', 'a\rb', '"a\\rb"'],
        ['a NUL character', 'a\u0000b', '"a\\u0000b"'],
        ['a C1 control character', 'a\u0085b', '"a\\u0085b"'],
        ['a DEL character', 'a\u007fb', '"a\\u007fb"'],
        ['a line separator', 'a\u2028b', '"a\\u2028b"'],
        ['a paragraph separator', 'a\u2029b', '"a\\u2029b"'],
        ['a lone surrogate', '\ud800', '"\\ud800"'],
        ['a single quote', "a'b", '"a\'b"'],
        ['a snippet placeholder', 'a$1b', '"a$1b"'],
        ['an empty name', '', '""'],
    ])('escapes %s into a valid Python literal', (_case, text, expected) => {
        expect(pythonStringLiteral(text)).toBe(expected);
    });
});
