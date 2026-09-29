import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

@Component({
    selector: 'app-stop-button',
    imports: [MatTooltipModule, AppSvgIconComponent],
    templateUrl: './stop-button.component.html',
    styleUrls: ['./stop-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StopButtonComponent {
    tooltip = input('Stop');
    disabled = input(false);

    triggered = output<void>();
}
