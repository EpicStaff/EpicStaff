import { renderChatMarkdown } from './chat-markdown.util';

describe('renderChatMarkdown', () => {
    it('renders bold, lists and line breaks', () => {
        expect(renderChatMarkdown('**Velour Assistant**')).toContain('<strong>Velour Assistant</strong>');
        expect(renderChatMarkdown('- a\n- b')).toContain('<li>a</li>');
        expect(renderChatMarkdown('a\nb')).toContain('<br>');
    });
    it('shows raw HTML as text', () => {
        const html = renderChatMarkdown('<img src=x onerror=alert(1)> and <b>bold</b>');
        expect(html).not.toContain('<img');
        expect(html).toContain('&lt;img');
        expect(html).not.toContain('<b>');
    });
    it('shows a block of raw HTML as text', () => {
        const html = renderChatMarkdown('<script>alert(1)</script>');
        expect(html).not.toContain('<script');
        expect(html).toContain('&lt;script&gt;');
    });
    it('renders Markdown images as their escaped alt text', () => {
        const html = renderChatMarkdown('![Clinic map](https://x/y.png)');
        expect(html).not.toContain('<img');
        expect(html).toContain('Clinic map');
        expect(renderChatMarkdown('![<b>x</b>](https://x/y.png)')).toContain('&lt;b&gt;x&lt;/b&gt;');
    });
    it('opens links in a new tab and drops script links', () => {
        expect(renderChatMarkdown('[site](https://example.com)')).toContain('target="_blank"');
        expect(renderChatMarkdown('[site](https://example.com)')).toContain('rel="noopener noreferrer"');
        expect(renderChatMarkdown('[x](javascript:alert(1))')).not.toContain('javascript:');
    });
});
