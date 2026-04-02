import { ChangeDetectionStrategy, Component, HostBinding, input } from '@angular/core';

import { InlineSvgDirective } from '../../../core/directives/inline-svg.directive';

@Component({
    selector: 'app-icon',
    standalone: true,
    imports: [InlineSvgDirective],
    template: `
        <span
            class="app-icon"
            [style.width]="size()"
            [style.height]="size()"
            appInlineSvg
            [path]="iconPath"
            [svgSize]="size()"
            [attr.aria-label]="ariaLabel()"
            aria-hidden="true"
        ></span>
    `,
    styles: [
        `
            :host {
                display: flex;
                justify-content: center;
                align-items: center;
                flex-shrink: 0;
            }

            :host(.rounded) {
                border-radius: 50%;
                cursor: pointer;
                &:hover {
                    transition: 0.3s;
                    background-color: var(--color-ks-hover-row);
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppIconComponent {
    icon = input.required<string>();
    ariaLabel = input<string>('');
    size = input<string>('2rem');
    isAction = input<boolean>(false);

    @HostBinding('class.rounded')
    get isRounded() {
        return this.isAction();
    }

    get iconPath(): string {
        return this.icon() ? `assets/icons/${this.icon()}.svg` : '';
    }
}
