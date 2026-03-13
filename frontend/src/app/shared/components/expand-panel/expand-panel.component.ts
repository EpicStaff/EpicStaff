import { ChangeDetectionStrategy, Component, input, signal } from "@angular/core";
import { TooltipComponent } from "@shared/components";
import { expandCollapseAnimation } from "@shared/animations";
import { NgClass } from "@angular/common";

@Component({
    selector: 'app-expand-panel',
    templateUrl: './expand-panel.component.html',
    styleUrls: ['./expand-panel.component.scss'],
    animations: [expandCollapseAnimation],
    imports: [
        TooltipComponent,
        NgClass
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ExpandPanelComponent {
    icon = input<string>('help_outline');
    label = input<string>('Expand');
    required = input<boolean>(false);
    tooltipText = input<string>('');
    expanded = input<boolean>(false);

    expandedState = signal<boolean>(this.expanded());
}
