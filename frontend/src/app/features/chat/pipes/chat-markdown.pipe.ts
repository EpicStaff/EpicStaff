import { Pipe, PipeTransform } from '@angular/core';

import { renderChatMarkdown } from '../utils/chat-markdown.util';

/**
 * A Markdown message as sanitized HTML for `[innerHTML]`. Pure, so a message is parsed once, not on every check.
 * Angular sanitizes the binding again; it keeps the links' target and rel.
 */
@Pipe({
    name: 'chatMarkdown',
})
export class ChatMarkdownPipe implements PipeTransform {
    transform(markdown: string): string {
        return renderChatMarkdown(markdown);
    }
}
