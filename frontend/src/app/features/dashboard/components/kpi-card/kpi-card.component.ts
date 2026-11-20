import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
    selector: 'app-kpi-card',
    templateUrl: './kpi-card.component.html',
    styleUrls: ['./kpi-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KpiCardComponent {
    readonly icon = input.required<string>();
    readonly label = input.required<string>();
    readonly value = input.required<string | number>();
    readonly unit = input('');
}
