import { escapeHtml } from '@shared/utils';
import { Parser, Token } from 'marked';
import { MARKED_OPTIONS, MarkedOptions, MarkedRenderer } from 'ngx-markdown';

/**
 * Hardened MarkedOptions for the global `provideMarkdown()`:
 *
 * - **Images** render as clickable links instead of `<img>` tags, preventing
 *   no-click data exfiltration via injected markdown in LLM/model output.
 * - **Links** open in a new tab with `rel="noopener noreferrer"`.
 */
export function safeMarkdownOptionsFactory(): MarkedOptions {
    const renderer = new MarkedRenderer();

    renderer.image = ({ href, title, text }: { href: string; title: string | null; text: string }) => {
        const label = text || title || href;
        return `<a href="${escapeHtml(href)}" rel="noopener noreferrer" target="_blank" title="Open image: ${escapeHtml(label)}">[image: ${escapeHtml(label)}]</a>`;
    };

    renderer.link = ({ href, title, tokens }: { href: string; title?: string | null; tokens: Token[] }) => {
        const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
        const body = Parser.parseInline(tokens);
        return `<a href="${escapeHtml(href)}" rel="noopener noreferrer" target="_blank"${titleAttr}>${body}</a>`;
    };

    return { renderer, gfm: true };
}

export const SAFE_MARKED_OPTIONS_PROVIDER = {
    provide: MARKED_OPTIONS,
    useFactory: safeMarkdownOptionsFactory,
};
