import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

export type StopButtonVariant = 'pause' | 'stop';

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
    variant = input<StopButtonVariant>('pause');

    triggered = output<void>();
}
