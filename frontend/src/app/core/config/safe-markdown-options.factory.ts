import { escapeHtml } from '@shared/utils';
import { Parser, Token } from 'marked';
import { MARKED_OPTIONS, MarkedOptions, MarkedRenderer } from 'ngx-markdown';

const ALLOWED_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);

/**
 * Hardened MarkedOptions for the global `provideMarkdown()`:
 *
 * - **Images** render as clickable links instead of `<img>` tags, preventing
 *   no-click data exfiltration via injected markdown in LLM/model output.
 * - **Links** open in a new tab with `rel="noopener noreferrer"`.
 * - **URI schemes** are restricted to http, https, mailto — blocks `javascript:`, `data:`, etc.
 */
export function safeMarkdownOptionsFactory(): MarkedOptions {
    const renderer = new MarkedRenderer();

    renderer.image = ({ href, title, text }: { href: string; title: string | null; text: string }) => {
        const label = text || title || href;
        const safeHref = sanitizeHref(href);
        if (!safeHref) {
            return `[image: ${escapeHtml(label)}]`;
        }
        return `<a href="${escapeHtml(safeHref)}" rel="noopener noreferrer" target="_blank" title="Open image: ${escapeHtml(label)}">[image: ${escapeHtml(label)}]</a>`;
    };

    renderer.link = ({ href, title, tokens }: { href: string; title?: string | null; tokens: Token[] }) => {
        const safeHref = sanitizeHref(href);
        const body = Parser.parseInline(tokens);
        if (!safeHref) {
            return body;
        }
        const titleAttr = title ? ` title="${escapeHtml(title)}"` : '';
        return `<a href="${escapeHtml(safeHref)}" rel="noopener noreferrer" target="_blank"${titleAttr}>${body}</a>`;
    };

    return { renderer, gfm: true };
}

export const SAFE_MARKED_OPTIONS_PROVIDER = {
    provide: MARKED_OPTIONS,
    useFactory: safeMarkdownOptionsFactory,
};

function sanitizeHref(href: string): string | null {
    try {
        const url = new URL(href, window.location.href);
        return ALLOWED_PROTOCOLS.has(url.protocol) ? href : null;
    } catch {
        return null;
    }
}
