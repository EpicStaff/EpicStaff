import { ChangeDetectionStrategy, Component, computed, EventEmitter, Input, input, Output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-icon-button',
    imports: [AppSvgIconComponent, MatTooltip],
    template: `
        <button
            type="button"
            class="icon-button"
            [style.width]="size"
            [style.height]="size"
            (click)="onButtonClick()"
            [disabled]="disabled"
            [attr.aria-label]="ariaLabel() || tooltip() || null"
            [matTooltip]="tooltipText()"
        >
            <app-svg-icon
                [icon]="icon"
                [size]="iconSize"
            />
        </button>
    `,
    changeDetection: ChangeDetectionStrategy.Eager,
    styles: [
        `
            .icon-button {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border: none;
                background: transparent;
                cursor: pointer;
                border-radius: 4px;
                transition: background-color 0.2s ease;
                padding: 0;

                &:is(:hover, :focus-visible):not(:disabled) {
                    background-color: var(--white-alpha-10);
                }

                &:active:not(:disabled) {
                    background-color: var(--white-alpha-15);
                }

                &:disabled {
                    cursor: not-allowed;
                    opacity: 0.5;
                }

                app-svg-icon {
                    // Overridable from outside: set the custom property on the <app-icon-button> element.
                    color: var(--icon-button-icon-color, var(--white));
                }
            }
        `,
    ],
})
export class IconButtonComponent {
    @Input() icon: string = '';
    @Input() size: string = '1.5rem';
    readonly ariaLabel = input('');
    /** Shown on hover and keyboard focus; falls back to `ariaLabel`, so each one alone names the button. */
    readonly tooltip = input('');
    @Input() disabled: boolean = false;
    @Output() onClick = new EventEmitter<void>();

    protected readonly tooltipText = computed(() => this.tooltip() || this.ariaLabel());

    get iconSize(): string {
        const sizeValue = parseFloat(this.size);
        const unit = this.size.replace(/[\d.]/g, '');
        return `${sizeValue * 0.6}${unit}`;
    }

    onButtonClick(): void {
        if (!this.disabled) {
            this.onClick.emit();
        }
    }
}
