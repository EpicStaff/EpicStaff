import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

@Component({
    selector: 'app-project-transition',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="project-transition">
            <div class="divider">
                <div class="line"></div>
                <!-- <div class="transition-text">Project Transition</div> -->
                <div class="line"></div>
            </div>
        </div>
    `,
    styles: [
        `
            .project-transition {
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

            .transition-text {
                padding: 0 1rem;
                color: var(--gray-500);
                font-size: 0.85rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
        `,
    ],
})
export class ProjectTransitionComponent {
    // You can add inputs if needed for customization
}
