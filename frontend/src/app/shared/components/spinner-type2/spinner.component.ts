import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

@Component({
    selector: 'app-spinner2',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="spinner-container" [style.width.px]="size" [style.height.px]="size">
            <i class="ti ti-loader spinner" [style.font-size.px]="iconSize"></i>
        </div>
    `,
    styles: [
        `
            .spinner-container {
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .spinner {
                animation: spin 1s linear infinite;
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
    changeDetection: ChangeDetectionStrategy.OnPush,
})
//TODO use one spinner across app
export class Spinner2Component {
    @Input() size = 24; // Default size in pixels

    /**
     * Calculate the icon size based on the container size
     * We make the icon slightly smaller than the container for better visual balance
     */
    get iconSize(): number {
        return Math.max(this.size * 0.75, 12); // Ensure minimum size of 12px
    }
}
