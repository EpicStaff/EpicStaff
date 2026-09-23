import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-view-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './view-button.component.html',
    styleUrls: ['./view-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ViewButtonComponent {
    tooltip = input('View');
    disabled = input(false);

    triggered = output<void>();
}
