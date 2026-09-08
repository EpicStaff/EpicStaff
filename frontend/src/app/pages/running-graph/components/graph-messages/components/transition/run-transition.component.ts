import { ChangeDetectionStrategy, Component } from '@angular/core';

/** Horizontal divider drawn between two consecutive runs in the same session. */
@Component({
    selector: 'app-run-transition',
    imports: [],
    template: `
        <div class="run-transition">
            <div class="divider">
                <div class="line"></div>
                <div class="line"></div>
            </div>
        </div>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: [
        `
            .run-transition {
                padding: 2rem 0;
                width: 100%;
                margin-bottom: 0.8rem;
            }

            .divider {
                display: flex;
                align-items: center;
                width: 100%;
            }

            .line {
                flex-grow: 1;
                height: 1px;
                background-color: var(--gray-700);
            }
        `,
    ],
})
export class RunTransitionComponent {}
