import { escapeHtml } from '@shared/utils';
import DOMPurify from 'dompurify';
import { Marked } from 'marked';

// Chat replies come from flows and LLMs: raw HTML in them is shown as text, never rendered.
const chatMarked = new Marked({
    gfm: true,
    breaks: true,
    async: false,
    // Images would load third-party URLs, so only their alt text is shown, as the widget does.
    renderer: { html: ({ text }) => escapeHtml(text), image: ({ text }) => escapeHtml(text) },
});

// An instance of its own, so its link hook never reaches other DOMPurify users in the app.
const purifier = DOMPurify();
purifier.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A') {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer');
    }
});

/**
 * Sanitized HTML for a bot or operator message written in Markdown. Images show only their alt text (they would load
 * third-party URLs), nor task-list checkboxes (Angular's sanitizer would strip them anyway).
 */
export function renderChatMarkdown(markdown: string): string {
    const html = chatMarked.parse(markdown) as string;
    return purifier.sanitize(html, { ADD_ATTR: ['target'], FORBID_TAGS: ['img', 'input', 'style'] });
}
