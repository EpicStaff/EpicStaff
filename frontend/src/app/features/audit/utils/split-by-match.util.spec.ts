import { splitByMatch } from './split-by-match.util';

describe('splitByMatch', () => {
    it('returns the whole text as one non-match segment when the term is empty or whitespace', () => {
        expect(splitByMatch('hello world', '')).toEqual([{ text: 'hello world', isMatch: false }]);
        expect(splitByMatch('hello world', '   ')).toEqual([{ text: 'hello world', isMatch: false }]);
    });

    it('splits around a single match', () => {
        expect(splitByMatch('hello world', 'lo w')).toEqual([
            { text: 'hel', isMatch: false },
            { text: 'lo w', isMatch: true },
            { text: 'orld', isMatch: false },
        ]);
    });

    it('marks every occurrence', () => {
        expect(splitByMatch('abcabca', 'a')).toEqual([
            { text: 'a', isMatch: true },
            { text: 'bc', isMatch: false },
            { text: 'a', isMatch: true },
            { text: 'bc', isMatch: false },
            { text: 'a', isMatch: true },
        ]);
    });

    it('matches case-insensitively and keeps the original casing', () => {
        expect(splitByMatch('Agent AGENT agent', 'aGeNt')).toEqual([
            { text: 'Agent', isMatch: true },
            { text: ' ', isMatch: false },
            { text: 'AGENT', isMatch: true },
            { text: ' ', isMatch: false },
            { text: 'agent', isMatch: true },
        ]);
    });

    it('handles matches at the start and the end', () => {
        expect(splitByMatch('flow name flow', 'flow')).toEqual([
            { text: 'flow', isMatch: true },
            { text: ' name ', isMatch: false },
            { text: 'flow', isMatch: true },
        ]);
    });

    it('trims the term before matching', () => {
        expect(splitByMatch('a task b', '  task ')).toEqual([
            { text: 'a ', isMatch: false },
            { text: 'task', isMatch: true },
            { text: ' b', isMatch: false },
        ]);
    });

    it('treats regex special characters literally', () => {
        expect(splitByMatch('cost (a+b)* is $1.00', '(a+b)*')).toEqual([
            { text: 'cost ', isMatch: false },
            { text: '(a+b)*', isMatch: true },
            { text: ' is $1.00', isMatch: false },
        ]);
        expect(splitByMatch('abc', '.')).toEqual([{ text: 'abc', isMatch: false }]);
    });
});
