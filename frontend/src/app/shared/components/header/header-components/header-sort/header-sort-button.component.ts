import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Output } from '@angular/core';

@Component({
    selector: 'app-project-sort-button',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="projects-page-sort-dropdown">
            <button class="projects-page-sort-btn" (click)="onSort()" aria-label="Sort projects">
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
                    class="icon icon-tabler icons-tabler-outline icon-tabler-arrows-sort"
                >
                    <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                    <path d="M3 9l4 -4l4 4m-4 -4v14" />
                    <path d="M21 15l-4 4l-4 -4m4 4v-14" />
                </svg>
            </button>
        </div>
    `,
    styles: [
        `
            .projects-page-sort-dropdown {
                position: relative;

                .projects-page-sort-btn {
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
export class ProjectSortButtonComponent {
    @Output() sortEvent = new EventEmitter<void>();

    onSort(): void {
        this.sortEvent.emit();
    }
}
