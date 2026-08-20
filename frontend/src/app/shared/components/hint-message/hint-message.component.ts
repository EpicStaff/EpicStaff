import { Component } from '@angular/core';

/** Small accent-colored callout for a short inline hint under a form field. Content is projected
 *  so callers can still bold part of the message (e.g. `<strong>Secrets tab</strong>`). */
@Component({
    selector: 'app-hint-message',
    template: `
        <div class="hint-message">
            <ng-content />
        </div>
    `,
    styles: [
        `
            .hint-message {
                margin: 0.5rem 0 0;
                padding: 8px 12px;
                border-left: 3px solid var(--accent-color);
                border-radius: 4px;
                background: var(--color-ghost-btn-hover);
                font-family: 'Inter', sans-serif;
                font-weight: 400;
                font-size: 14px;
                line-height: 130%;
                letter-spacing: 0;
                color: var(--accent-color);

                strong {
                    font-weight: 700;
                }
            }
        `,
    ],
})
export class HintMessageComponent {}
