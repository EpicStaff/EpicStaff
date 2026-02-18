import {
    Component,
    input,
    ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HelpTooltipComponent } from '../help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-tooltip',
    standalone: true,
    imports: [CommonModule, HelpTooltipComponent],
    template: `
        <div class="tooltip-label-container">
            <label class="tooltip-label">
                <span class="tooltip-label-text">{{ label() }}</span>
                @if (required()) {
                    <span class="tooltip-label-required">*</span>
                }
            </label>
            @if (tooltipText()) {
                <app-help-tooltip
                    [text]="tooltipText()"
                    position="right"
                ></app-help-tooltip>
            }
        </div>
    `,
    styles: [
        `
            .tooltip-label-container {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.75rem;
            }

            .tooltip-label {
                display: flex;
                align-items: center;
                gap: 0.25rem;
                font-size: 0.875rem;
                font-weight: 500;
                color: rgba(217, 217, 222, 0.6);
                margin: 0;
            }

            .tooltip-label-text {
                line-height: 1.3;
            }

            .tooltip-label-required {
                color: #9c2e2e;
                line-height: 1.3;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TooltipComponent {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
}

