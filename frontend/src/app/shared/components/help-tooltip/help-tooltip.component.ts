import { ChangeDetectionStrategy, Component, Input, input } from '@angular/core';
import { MatTooltipModule, TooltipPosition } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

/**
 * A help icon whose tooltip explains the field next to it. The icon sits in a real button
 * so keyboard and screen-reader users can reach the text: the button takes focus, Material
 * opens the tooltip on focus and links the text with `aria-describedby`. `type="button"` keeps it
 * from submitting a form, and it has no click handler of its own — but clicks and keys still bubble
 * to its ancestors, so don't place it inside a clickable element. Inside a `<label>`, link the label
 * to its control with `for`; otherwise the button becomes the label's control.
 */
@Component({
    selector: 'app-help-tooltip',
    imports: [AppSvgIconComponent, MatTooltipModule],
    template: `
        <div class="help-tooltip-container">
            <button
                type="button"
                class="help-icon-wrapper"
                [attr.aria-label]="ariaLabel()"
                [matTooltip]="text"
                [matTooltipPosition]="tooltipPosition"
                [matTooltipClass]="tooltipClass"
            >
                @if (iconClass) {
                    <i
                        [class]="iconClass + ' class-icon'"
                        aria-hidden="true"
                    ></i>
                } @else {
                    <app-svg-icon
                        [icon]="icon"
                        [size]="size"
                        [width]="width()"
                        [height]="height()"
                    />
                }
            </button>
        </div>
    `,
    styles: [
        `
            .help-tooltip-container {
                position: relative;
                display: flex;
                align-items: center;
            }

            .help-icon-wrapper {
                cursor: help;
                display: flex;
                align-items: center;
                justify-content: center;
                width: 16px;
                height: 16px;
                flex-shrink: 0;
                margin: 0;
                padding: 0;
                border: none;
                border-radius: 2px;
                background: none;
                font: inherit;
                outline: none;
                color: var(--accent-color);
                transition: opacity 0.2s ease;

                &:hover {
                    opacity: 0.7;
                }

                &:focus-visible {
                    outline: 2px solid var(--accent-color);
                    outline-offset: 2px;
                }
            }

            .class-icon {
                font-size: 1rem;
                line-height: 1;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HelpTooltipComponent {
    @Input() text = '';
    /** The button's accessible name; name the field it explains (`"Email help"`) to tell help buttons apart. */
    readonly ariaLabel = input('Help');
    @Input() position: 'top' | 'bottom' | 'left' | 'right' = 'right';
    @Input() icon = 'help';
    @Input() iconClass = '';
    @Input() size = '16px';
    /** Override `size` on one axis for a non-square icon; passed through to `app-svg-icon`. */
    readonly width = input<string>();
    readonly height = input<string>();
    @Input() tooltipClass = '';

    get tooltipPosition(): TooltipPosition {
        if (this.position === 'top') {
            return 'above';
        }
        if (this.position === 'bottom') {
            return 'below';
        }
        return this.position;
    }
}
