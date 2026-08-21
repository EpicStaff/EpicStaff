import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

export type ButtonRoundVariant = 'primary' | 'secondary';

const DEFAULT_COLOR = 'var(--accent-color, #685fff)';
const ON_ACCENT_ICON = 'var(--color-text-primary, #d9d9de)';

@Component({
    selector: 'app-button-round',
    standalone: true,
    imports: [AppSvgIconComponent],
    template: `
        <button
            type="button"
            class="btn-round"
            [class.btn-round--primary]="variant() === 'primary'"
            [class.btn-round--secondary]="variant() === 'secondary'"
            [style.--br-size.px]="size()"
            [style.--br-color]="color()"
            [style.--br-icon-color]="resolvedIconColor()"
            [style.--br-hover]="hoverColor() ?? defaultHover()"
            [style.--br-disabled]="disabledColor() ?? defaultDisabled()"
            [attr.aria-label]="ariaLabel()"
            [disabled]="disabled()"
        >
            <app-svg-icon
                [icon]="icon()"
                [size]="iconSize() + 'px'"
            />
        </button>
    `,
    styleUrls: ['./button-round.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ButtonRoundComponent {
    readonly icon = input.required<string>();
    readonly variant = input<ButtonRoundVariant>('primary');
    readonly size = input<number>(40);
    readonly iconSize = input<number>(16);
    readonly color = input<string>(DEFAULT_COLOR);
    readonly iconColor = input<string | null>(null);
    readonly hoverColor = input<string | null>(null);
    readonly disabledColor = input<string | null>(null);
    readonly disabled = input<boolean>(false);
    readonly ariaLabel = input<string | null>(null);

    readonly resolvedIconColor = computed<string>(
        () => this.iconColor() ?? (this.variant() === 'primary' ? ON_ACCENT_ICON : this.color())
    );

    readonly defaultHover = computed<string>(() =>
        this.variant() === 'primary'
            ? `color-mix(in srgb, ${this.color()} 40%, transparent)`
            : `color-mix(in srgb, ${this.color()} 8%, transparent)`
    );

    readonly defaultDisabled = computed<string>(() => `color-mix(in srgb, ${this.color()} 40%, transparent)`);
}
