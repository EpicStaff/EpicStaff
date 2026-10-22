import { Component, input } from '@angular/core';

/** `accent`: a plain hint. `warning`: a consequence the user should notice — amber text and rail on an
 *  amber tint, with bold words in the primary text colour (close to, not a copy of, the permission banners). */
export type HintMessageTone = 'accent' | 'warning';

/** Small colored callout for a short inline hint under a form field. Content is projected
 *  so callers can still bold part of the message (e.g. `<strong>Secrets tab</strong>`). */
@Component({
    selector: 'app-hint-message',
    template: `
        <div
            class="hint-message"
            [class.hint-message--warning]="tone() === 'warning'"
        >
            <ng-content />
        </div>
    `,
    styles: [
        `
            // The space above sits on the host, so a caller can override it with a plain rule.
            :host {
                display: block;
                margin-top: 0.5rem;
            }

            .hint-message {
                padding: 8px 12px;
                border-left: 3px solid var(--accent-color);
                border-radius: 4px;
                background: var(--color-ghost-btn-hover);
                font-weight: var(--text-body-weight);
                font-size: var(--text-body-size);
                line-height: var(--text-body-line-height);
                letter-spacing: 0;
                color: var(--accent-color);

                strong {
                    font-weight: 700;
                }

                &--warning {
                    border-left-color: var(--color-warning);
                    background: color-mix(in srgb, var(--color-warning) 10%, transparent);
                    color: var(--color-warning);

                    strong {
                        color: var(--color-text-primary);
                    }
                }
            }
        `,
    ],
})
export class HintMessageComponent {
    readonly tone = input<HintMessageTone>('accent');
}
