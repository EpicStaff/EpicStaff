import { highlightQuery } from './highlight-query.util';

const keywordsOf = (query: string) =>
    highlightQuery(query)
        .filter((part) => part.isKeyword)
        .map((part) => part.text);

describe('highlightQuery', () => {
    it('marks field names, operators and keywords but not values', () => {
        expect(keywordsOf('error is not empty and not session_id == 66')).toEqual([
            'error',
            'is',
            'not',
            'empty',
            'and',
            'not',
            'session_id',
            '==',
        ]);
    });

    it('keeps quoted text and bare values plain, even when they look like keywords', () => {
        expect(keywordsOf('name == "not empty" or input : order1234')).toEqual(['name', '==', 'or', 'input', ':']);
    });

    it('marks the field before in / not in, not the listed values', () => {
        expect(keywordsOf('kind not in (session, node)')).toEqual(['kind', 'not', 'in']);
    });

    it('reproduces the query text exactly, including characters the grammar rejects', () => {
        const query = 'flow_name == "a" & ?';
        expect(
            highlightQuery(query)
                .map((part) => part.text)
                .join('')
        ).toBe(query);
    });
});
