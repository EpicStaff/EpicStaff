import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

@Component({
    selector: 'app-spinner',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div
            class="custom-loader"
            [ngClass]="{ overlay: isOverlay }"
            [ngStyle]="{
                'background-color': isOverlay ? backgroundColor : 'transparent',
            }"
        >
            <div
                class="spinner"
                [ngStyle]="{
                    width: size + 'px',
                    height: size + 'px',
                    border: borderWidth + 'px solid ' + borderColor,
                    'border-top-color': accentColor,
                }"
            ></div>
            <div
                *ngIf="text"
                class="loading-text"
                [ngStyle]="{ color: textColor, 'font-size': textSize + 'px' }"
            >
                {{ text }}
            </div>
        </div>
    `,
    styles: [
        `
            .custom-loader {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                z-index: 10;
                border-radius: 4px;
                padding: 20px;
            }

            .overlay {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
            }

            .spinner {
                flex-shrink: 0;
                border-radius: 50%;
                animation: spin 1s ease-in-out infinite;
                margin-bottom: 16px;
            }

            .loading-text {
                font-weight: 500;
            }

            @keyframes spin {
                to {
                    transform: rotate(360deg);
                }
            }
        `,
    ],
})
export class SpinnerComponent {
    @Input() size: number = 48;
    @Input() borderWidth: number = 4;
    @Input() text: string = '';
    @Input() accentColor: string = '#6562f5';
    @Input() borderColor: string = 'rgba(101, 98, 245, 0.3)';
    @Input() backgroundColor: string = '#171717';
    @Input() textColor: string = '#aaa';
    @Input() textSize: number = 16;
    @Input() isOverlay: boolean = true;
}
