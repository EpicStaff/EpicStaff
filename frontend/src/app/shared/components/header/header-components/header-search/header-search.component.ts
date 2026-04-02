import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-project-search',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="projects-page-search" [class.projects-page-search-has-content]="searchTerm.trim().length > 0">
            <svg
                xmlns="http://www.w3.org/2000/svg"
                width="20"
                height="20"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                viewBox="0 0 24 24"
            >
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="16" y1="16" x2="21.5" y2="21.5"></line>
            </svg>

            <input
                type="text"
                class="projects-page-search-input"
                [placeholder]="placeholder"
                [value]="searchTerm"
                (input)="onInputChange($event)"
            />
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
            }

            .projects-page-search {
                display: flex;
                align-items: center;
                padding: 0.4rem 0.7rem;
                width: 240px;
                height: 36px;
                transition: all 0.2s ease;
                background-color: rgba(255, 255, 255, 0.04);
                border-radius: 6px;

                &.projects-page-search-has-content {
                    svg {
                        color: var(--accent-color);
                    }
                }

                &:focus-within {
                    background-color: rgba(255, 255, 255, 0.06);

                    svg {
                        color: var(--accent-color);
                    }
                }

                svg {
                    flex-shrink: 0;
                    width: 16px;
                    height: 16px;
                    color: #6b7280;
                    transition: color 0.2s ease;
                }

                .projects-page-search-input {
                    border: none;
                    background: transparent;
                    outline: none;
                    font-size: 14px;
                    color: #f9fafb;
                    width: 100%;
                    height: 100%;
                    margin-left: 0.5rem;

                    &::placeholder {
                        color: #6b7280;
                        font-weight: 400;
                        font-size: 14px;
                    }
                }
            }
        `,
    ],
})
export class ProjectSearchComponent {
    @Input() searchTerm: string = '';
    @Input() placeholder: string = '';
    @Output() searchInput = new EventEmitter<string>();

    onInputChange(event: Event): void {
        const value = (event.target as HTMLInputElement).value;
        this.searchInput.emit(value);
    }
}
