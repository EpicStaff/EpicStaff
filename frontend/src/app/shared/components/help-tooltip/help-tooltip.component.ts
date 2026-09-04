import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { MatTooltipModule, TooltipPosition } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-help-tooltip',
    imports: [AppSvgIconComponent, MatTooltipModule],
    template: `
        <div class="help-tooltip-container">
            @if (iconClass) {
                <i
                    [class]="iconClass + ' help-icon-wrapper class-icon'"
                    [matTooltip]="text"
                    [matTooltipPosition]="tooltipPosition"
                    [matTooltipClass]="tooltipClass"
                ></i>
            } @else {
                <app-svg-icon
                    [icon]="icon"
                    [size]="size"
                    class="help-icon-wrapper"
                    [matTooltip]="text"
                    [matTooltipPosition]="tooltipPosition"
                    [matTooltipClass]="tooltipClass"
                />
            }
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
                outline: none;
                color: var(--accent-color, #685fff);
                transition: opacity 0.2s ease;
                width: 16px;
                height: 16px;
                flex-shrink: 0;

                &:hover {
                    opacity: 0.7;
                }

                &.class-icon {
                    font-size: 16px;
                    line-height: 1;
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HelpTooltipComponent {
    @Input() text = '';
    @Input() position: 'top' | 'bottom' | 'left' | 'right' = 'right';
    @Input() icon = 'help';
    @Input() iconClass = '';
    @Input() size = '16px';
    @Input() tooltipClass = 'custom-tooltip';

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
