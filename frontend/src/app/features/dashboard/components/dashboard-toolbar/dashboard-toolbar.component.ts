import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { IconButtonComponent, NumberStepperComponent, SelectComponent, SelectItem } from '@shared/components';

import { DashboardPeriodUnit } from '../../models/dashboard-filters.model';
import { DashboardFiltersService } from '../../services/dashboard-filters.service';

const UNIT_ITEMS: SelectItem<DashboardPeriodUnit>[] = [
    { name: 'Days', value: DashboardPeriodUnit.Day },
    { name: 'Months', value: DashboardPeriodUnit.Month },
    { name: 'Years', value: DashboardPeriodUnit.Year },
];

@Component({
    selector: 'app-dashboard-toolbar',
    imports: [IconButtonComponent, NumberStepperComponent, SelectComponent],
    templateUrl: './dashboard-toolbar.component.html',
    styleUrls: ['./dashboard-toolbar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardToolbarComponent {
    protected readonly filtersService = inject(DashboardFiltersService);

    protected readonly unitItems = UNIT_ITEMS;
    protected readonly filters = this.filtersService.filters;

    protected onPeriodChange(value: number | null): void {
        if (value !== null) this.filtersService.setPeriod(value);
    }

    protected onUnitChange(value: unknown): void {
        this.filtersService.setUnit(value as DashboardPeriodUnit);
    }
}
