import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-flow-shortcuts-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './flow-shortcuts-button.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./flow-shortcuts-button.component.scss'],
})
export class FlowShortcutsButtonComponent {
    icon = input<string>('shortcut');
    iconSize = input<string>('12px');
    /** Moves the icon vertically, for icons whose drawing sits off-centre in their box. */
    iconOffsetY = input<string>('0px');
    active = input<boolean>(false);
    /** The button's name for screen readers; the button shows only an icon. */
    ariaLabel = input<string>('Keyboard shortcuts');
    tooltip = input<string>('Keyboard shortcuts');

    clicked = output<void>();
}
