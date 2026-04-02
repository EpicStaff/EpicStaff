import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';

@Component({
    selector: 'app-project-filter-button',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="projects-page-filter-dropdown">
            <button class="projects-page-filter-btn" (click)="onFilter()" aria-label="Filter projects">
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    class="icon icon-tabler icons-tabler-outline icon-tabler-filter"
                >
                    <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                    <path
                        d="M4 4h16v2.172a2 2 0 0 1 -.586 1.414l-4.414 4.414v7l-6 2v-8.5l-4.48 -4.928a2 2 0 0 1 -.52 -1.345v-2.227z"
                    />
                </svg>
            </button>
        </div>
    `,
    styles: [
        `
            .projects-page-filter-dropdown {
                position: relative;

                .projects-page-filter-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background-color: rgba(255, 255, 255, 0.04);
                    padding: 0.4rem;
                    width: 36px;
                    height: 36px;
                    border-radius: 6px;
                    color: #6b7280;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    border: none;

                    &:hover {
                        color: #8b5cf6;
                        background-color: rgba(139, 92, 246, 0.08);
                    }

                    &:focus {
                        outline: none;
                        background-color: rgba(255, 255, 255, 0.06);
                    }

                    svg {
                        width: 20px;
                        height: 20px;
                        display: block;
                        transition: color 0.2s ease;
                    }
                }
            }
        `,
    ],
})
export class ProjectFilterButtonComponent {
    @Output() filterEvent = new EventEmitter<void>();

    onFilter(): void {
        this.filterEvent.emit();
    }
}
