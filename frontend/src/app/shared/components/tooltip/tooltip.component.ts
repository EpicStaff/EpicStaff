import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { HelpTooltipComponent } from '../help-tooltip';

@Component({
    selector: 'app-tooltip',
    imports: [HelpTooltipComponent],
    templateUrl: './tooltip.component.html',
    styleUrls: ['./tooltip.component.scss'],

    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TooltipComponent {
    icon = input<string>('help_outline');
    label = input<string>('');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    inline = input<boolean>(false);

    /** Names the help button after its field, so a form's help buttons are told apart. */
    protected readonly helpLabel = computed(() => (this.label() ? `${this.label()} help` : 'Help'));
}
