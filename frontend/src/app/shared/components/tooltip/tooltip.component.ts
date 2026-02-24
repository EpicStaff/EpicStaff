import {
    Component,
    input,
    ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HelpTooltipComponent } from '../help-tooltip';

@Component({
    selector: 'app-tooltip',
    imports: [CommonModule, HelpTooltipComponent],
    templateUrl: './tooltip.component.html',
    styleUrls: ['./tooltip.component.scss'],

    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TooltipComponent {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
}
