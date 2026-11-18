// Pins the HTML the highlight pipe produces: escaped text with matches wrapped in the grid's highlight mark. Unit layer.
import { HighlightPipe } from './highlight.pipe';

/** The exact markup the grid stylesheet targets. */
function mark(html: string): string {
    return `<mark class="grid-table-highlight">${html}</mark>`;
}

describe('HighlightPipe', () => {
    const pipe = new HighlightPipe();

    it('returns the escaped text when there is no search term', () => {
        expect(pipe.transform('Hello <World>', '')).toBe('Hello &lt;World&gt;');
    });

    it('wraps every case-insensitive match in the highlight mark and keeps the original casing', () => {
        expect(pipe.transform('World and WORLD', 'world')).toBe(`${mark('World')} and ${mark('WORLD')}`);
    });

    it('renders null and undefined as an empty string', () => {
        expect(pipe.transform(null, 'test')).toBe('');
        expect(pipe.transform(undefined, 'test')).toBe('');
    });

    it('stringifies non-string values before matching', () => {
        expect(pipe.transform(1234, '23')).toBe(`1${mark('23')}4`);
    });

    it('treats regular expression characters in the term literally', () => {
        expect(pipe.transform('price is $10.00 or 10500', '$10.00')).toBe(`price is ${mark('$10.00')} or 10500`);
    });

    it('escapes markup around and inside a match so a script tag can never be produced', () => {
        const result = pipe.transform('<script>alert("x")</script>', 'script');

        expect(result).toBe(`&lt;${mark('script')}&gt;alert(&quot;x&quot;)&lt;/${mark('script')}&gt;`);
        expect(result).not.toContain('<script');
    });

    it('matches a term containing angle brackets against the visible text', () => {
        expect(pipe.transform('a <b> c', '<b>')).toBe(`a ${mark('&lt;b&gt;')} c`);
    });

    it('matches an ampersand as typed, not inside the escaped entity', () => {
        expect(pipe.transform('Tom & Jerry', '&')).toBe(`Tom ${mark('&amp;')} Jerry`);
    });

    it('does not match entity text that is not in the raw value', () => {
        expect(pipe.transform('Tom & Jerry', 'amp')).toBe('Tom &amp; Jerry');
    });
});
