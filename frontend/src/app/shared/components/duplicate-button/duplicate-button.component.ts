import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-duplicate-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './duplicate-button.component.html',
    styleUrls: ['./duplicate-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DuplicateButtonComponent {
    tooltip = input('Copy');
    disabled = input(false);

    triggered = output<void>();
}
