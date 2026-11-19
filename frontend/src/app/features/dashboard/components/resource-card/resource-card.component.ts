import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { DashboardCardDetail } from '../../models/dashboard-card.model';

@Component({
    selector: 'app-resource-card',
    imports: [DecimalPipe],
    templateUrl: './resource-card.component.html',
    styleUrls: ['./resource-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ResourceCardComponent {
    readonly icon = input.required<string>();
    readonly label = input.required<string>();
    readonly value = input.required<number>();
    readonly details = input<DashboardCardDetail[]>([]);
}
