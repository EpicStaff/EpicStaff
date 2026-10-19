import { Component, ElementRef, input, output, viewChild } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

/**
 * A section's header in the conversations column: a heading whose button collapses and expands the section (the
 * accordion pattern). The column makes it sticky, so it stays on top while its section scrolls by.
 */
@Component({
    selector: 'app-conversation-section-header',
    imports: [AppSvgIconComponent],
    templateUrl: './conversation-section-header.component.html',
    styleUrl: './conversation-section-header.component.scss',
    host: {
        role: 'heading',
        'aria-level': '3',
    },
})
export class ConversationSectionHeaderComponent {
    readonly label = input.required<string>();
    readonly icon = input.required<string>();
    readonly isExpanded = input.required<boolean>();
    /** The id of the section body this header shows and hides. */
    readonly controlsId = input.required<string>();
    /** Only where the number is bounded and exact; null shows none. */
    readonly count = input<number | null>(null);
    readonly toggled = output<void>();

    private readonly button = viewChild.required<ElementRef<HTMLButtonElement>>('button');

    /** Takes the focus without a jump, then comes into view if it is not (the column's scroll padding applies). */
    focus(): void {
        const button = this.button().nativeElement;
        button.focus({ preventScroll: true });
        button.scrollIntoView({ block: 'nearest' });
    }
}
