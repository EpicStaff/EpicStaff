import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

@Component({
    selector: 'app-loading-spinner',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="loading-spinner-container">
            <div class="spinner" [ngClass]="size"></div>
            <div *ngIf="message" class="loading-message">{{ message }}</div>
        </div>
    `,
    styles: [
        `
            .loading-spinner-container {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 1.5rem 0;
            }
            .spinner {
                border: 4px solid #44474f;
                border-top: 4px solid #b0b8c1;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 1rem;
            }
            .spinner.sm {
                width: 32px;
                height: 32px;
                border-width: 3px;
            }
            .spinner.md {
                width: 48px;
                height: 48px;
                border-width: 4px;
            }
            .spinner.lg {
                width: 72px;
                height: 72px;
                border-width: 6px;
            }
            .loading-message {
                color: #b0b8c1;
                font-size: 1.1rem;
                font-weight: 500;
                text-align: center;
            }
            @keyframes spin {
                0% {
                    transform: rotate(0deg);
                }
                100% {
                    transform: rotate(360deg);
                }
            }
        `,
    ],
})
export class LoadingSpinnerComponent {
    @Input() size: 'sm' | 'md' | 'lg' = 'md';
    @Input() message?: string;
}
