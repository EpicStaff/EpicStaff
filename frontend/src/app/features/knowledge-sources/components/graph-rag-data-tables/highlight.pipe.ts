import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
    name: 'highlight',
    standalone: true,
})
export class HighlightPipe implements PipeTransform {
    transform(value: unknown, searchTerm: string): string {
        const text = value == null ? '' : String(value);
        const escaped = this.escapeHtml(text);

        if (!searchTerm) {
            return escaped;
        }

        const escapedSearch = this.escapeRegExp(searchTerm);
        const regex = new RegExp(`(${escapedSearch})`, 'gi');

        return escaped.replace(regex, '<mark class="data-tables__highlight">$1</mark>');
    }

    private escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    private escapeRegExp(text: string): string {
        return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
}
