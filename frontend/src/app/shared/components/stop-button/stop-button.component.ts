import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

@Component({
    selector: 'app-stop-button',
    imports: [MatTooltipModule],
    templateUrl: './stop-button.component.html',
    styleUrls: ['./stop-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StopButtonComponent {
    tooltip = input('Stop');
    disabled = input(false);

    triggered = output<void>();
}
