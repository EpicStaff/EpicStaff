import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
    selector: 'app-svg-icon',
    template: `
        <svg
            [style.width]="width() ?? size()"
            [style.height]="height() ?? size()"
            [attr.aria-label]="ariaLabel()"
            aria-hidden="true"
        >
            <use [attr.href]="'#icon-' + icon()" />
        </svg>
    `,
    styles: [
        `
            :host {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
            }
            svg {
                display: block;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppSvgIconComponent {
    icon = input.required<string>();
    ariaLabel = input<string>('');
    size = input<string>('24px');
    /** Overrides `size` on one axis, for icons that are not square. Falls back to `size()` when not provided. */
    width = input<string>();
    height = input<string>();
}
