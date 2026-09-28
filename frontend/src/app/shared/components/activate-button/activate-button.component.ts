import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-activate-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './activate-button.component.html',
    styleUrls: ['./activate-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ActivateButtonComponent {
    tooltip = input('Activate');
    disabled = input(false);

    triggered = output<void>();
}
