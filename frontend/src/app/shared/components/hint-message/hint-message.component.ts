import { Component, input } from '@angular/core';

/** `hint` (the default): an accent callout for a tip. `warning`: what the user should know before going on. */
export type HintMessageTone = 'hint' | 'warning';
/** `md` (the default): a callout under a form field. `sm`: one 28px line of small text, for a status in tight space. */
export type HintMessageSize = 'md' | 'sm';

/** Small colored callout for a short inline hint under a form field. Content is projected
 *  so callers can still bold part of the message (e.g. `<strong>Secrets tab</strong>`). */
@Component({
    selector: 'app-hint-message',
    template: `
        <div
            class="hint-message"
            [class.hint-message--warning]="tone() === 'warning'"
            [class.hint-message--sm]="size() === 'sm'"
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
            }

            // As the other warning callouts (restore warnings, webhook registration). No semantic subtle-warning
            // background token exists yet, so the same primitive they use.
            .hint-message--warning {
                border-left-color: var(--color-warning);
                background: var(--amber-alpha-8);
                color: var(--color-text-primary);
            }

            // At least 28px: one line of small text, centred; a longer message still wraps.
            .hint-message--sm {
                display: flex;
                align-items: center;
                min-height: 28px;
                padding: 4px 12px;
                box-sizing: border-box;
                font-weight: var(--text-body-small-weight);
                font-size: var(--text-body-small-size);
                line-height: var(--text-body-small-line-height);
            }
        `,
    ],
})
export class HintMessageComponent {
    readonly tone = input<HintMessageTone>('hint');
    readonly size = input<HintMessageSize>('md');
}
