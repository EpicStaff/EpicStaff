import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

@Component({
    selector: 'app-expand-panel',
    templateUrl: './expand-panel.component.html',
    styleUrls: ['./expand-panel.component.scss'],
    imports: [TooltipComponent, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExpandPanelComponent {
    icon = input<string>('help_outline');
    label = input<string>('Expand');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    expanded = input<boolean>(false);

    expandedState = signal<boolean>(this.expanded());
}
