import { toCsv } from './csv.util';

describe('toCsv', () => {
    it('joins cells with commas and rows with CRLF', () => {
        expect(
            toCsv([
                ['a', 1],
                ['b', 2],
            ])
        ).toBe('a,1\r\nb,2');
    });

    it('writes null and undefined as empty cells', () => {
        expect(toCsv([[null, undefined, 0]])).toBe(',,0');
    });

    it('quotes cells with commas, quotes or line breaks', () => {
        expect(toCsv([['a,b', 'say "hi"', 'two\nlines']])).toBe('"a,b","say ""hi""","two\nlines"');
    });

    it('stops text from running as a spreadsheet formula', () => {
        expect(toCsv([['=SUM(A1)', '+1', '@cmd', -5]])).toBe("'=SUM(A1),'+1,'@cmd,-5");
    });

    it('writes an empty row as an empty line', () => {
        expect(toCsv([['a'], [], ['b']])).toBe('a\r\n\r\nb');
    });
});
