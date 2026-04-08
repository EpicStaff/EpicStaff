import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-spinner2',
    standalone: true,
    imports: [AppSvgIconComponent],
    template: `
        <div class="spinner-container" [style.width.px]="size" [style.height.px]="size">
            <app-svg-icon icon="loader" [size]="iconSize + 'px'" class="spinner" />
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
// TODO use one spinner across app
export class Spinner2Component {
    @Input() size = 24;

    get iconSize(): number {
        return Math.max(this.size * 0.75, 12);
    }
}