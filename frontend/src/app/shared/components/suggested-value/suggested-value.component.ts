import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-suggested-value',
    imports: [TooltipComponent],
    templateUrl: './suggested-value.component.html',
    styleUrls: ['./suggested-value.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SuggestedValueComponent {
    label = input.required<string>();
    tooltipText = input<string>('');
    value = input<unknown>(null);
}
