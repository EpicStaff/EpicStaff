import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

/** Horizontal divider drawn between two consecutive runs in the same session. */
@Component({
    selector: 'app-run-transition',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="run-transition">
            <div class="divider">
                <div class="line"></div>
                <div class="line"></div>
            </div>
        </div>
    `,
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
