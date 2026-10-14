import { insertQueryText } from './insert-query-text.util';

describe('insertQueryText', () => {
    it('keeps both spaces between two characters and puts the cursor after the text', () => {
        expect(insertQueryText('ab', 1, 1, ' and ')).toEqual({ query: 'a and b', caret: 6 });
    });

    it('drops the leading space at the start of the query or after a space', () => {
        expect(insertQueryText('', 0, 0, ' not ')).toEqual({ query: 'not ', caret: 4 });
        expect(insertQueryText('a ', 2, 2, ' is ')).toEqual({ query: 'a is ', caret: 5 });
    });

    it('drops the trailing space before a space', () => {
        expect(insertQueryText('a b', 1, 1, ' == ')).toEqual({ query: 'a == b', caret: 4 });
    });

    it('replaces the selection', () => {
        expect(insertQueryText('a xyz b', 2, 5, ' or ')).toEqual({ query: 'a or b', caret: 4 });
    });

    it('puts the cursor inside the parentheses of in ()', () => {
        expect(insertQueryText('status', 6, 6, ' in ()', 1)).toEqual({ query: 'status in ()', caret: 11 });
    });
});
