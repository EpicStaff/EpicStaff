import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-project-create-button',
    standalone: true,
    template: `
        <button
            class="create-project-button"
            (click)="onCreate()"
        >
            <svg
                xmlns="http://www.w3.org/2000/svg"
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="icon icon-tabler icons-tabler-outline icon-tabler-plus"
            >
                <path
                    stroke="none"
                    d="M0 0h24v24H0z"
                    fill="none"
                />
                <path d="M12 5l0 14" />
                <path d="M5 12l14 0" />
            </svg>
            <span>{{ buttonTitle }}</span>
        </button>
    `,
    styles: [
        `
            .create-project-button {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                font-size: 14px;
                font-weight: 400;
                padding: 0.4rem 1.2rem;
                height: 36px;
                line-height: 14px;
                background-color: var(--accent-color);
                color: var(--white);
                border: none;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.2s ease;

                &:hover {
                    background-color: #7a73ff;
                    box-shadow: 0 4px 12px rgba(104, 95, 255, 0.3);
                }

                &:active {
                    box-shadow: 0 2px 4px rgba(104, 95, 255, 0.2);
                }

                svg {
                    margin-top: 2px;
                    color: var(--white);
                    stroke-width: 1.5;
                    color: var(--white);
                }
            }
        `,
    ],
})
export class ProjectCreateButtonComponent {
    @Input() buttonTitle: string = 'New Project';
    @Output() createEvent = new EventEmitter<void>();

    onCreate(): void {
        this.createEvent.emit();
    }
}
