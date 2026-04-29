import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-project-favorite-button',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <button
            class="projects-page-favorite-btn"
            [class.projects-page-favorite-btn-active]="active"
            (click)="onFavorite()"
            aria-label="Show favorites"
        >
            <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="icon icon-tabler icons-tabler-outline icon-tabler-star"
            >
                <path
                    stroke="none"
                    d="M0 0h24v24H0z"
                    fill="none"
                />
                <path
                    d="M12 17.75l-6.172 3.245l1.179 -6.873l-5 -4.867l6.9 -1l3.086 -6.253l3.086 6.253l6.9 1l-5 4.867l1.179 6.873z"
                />
            </svg>
        </button>
    `,
    styles: [
        `
            .projects-page-favorite-btn {
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

                &.projects-page-favorite-btn-active {
                    color: #ffd93d;
                    background-color: rgba(255, 217, 61, 0.08);
                }

                &:hover {
                    color: #ffd93d;
                    background-color: rgba(255, 217, 61, 0.08);
                }

                &:focus {
                    outline: none;
                    background-color: rgba(255, 255, 255, 0.06);
                }

                svg {
                    width: 20px;
                    height: 20px;
                    display: block;
                }
            }
        `,
    ],
})
export class ProjectFavoriteButtonComponent {
    @Input() active: boolean = false;
    @Output() favoriteToggle = new EventEmitter<void>();

    onFavorite(): void {
        this.favoriteToggle.emit();
    }
}
