import { inject, Injectable } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';

import { DashboardStats } from '../models/dashboard-stats.model';
import { toPreviousRange, toRange } from '../utils/dashboard-range.util';
import { DashboardApiService } from './dashboard-api.service';
import { DashboardFiltersService } from './dashboard-filters.service';

@Injectable()
export class DashboardStatsService {
    private readonly api = inject(DashboardApiService);
    private readonly filtersService = inject(DashboardFiltersService);

    readonly resource = rxResource({
        params: () => ({ filters: this.filtersService.filters(), refresh: this.filtersService.refreshCount() }),
        stream: ({ params: { filters } }) => {
            const current = toRange(filters);
            return forkJoin({
                current: this.api.getStats<DashboardStats>(current, filters.unit),
                previous: this.api.getStats<DashboardStats>(toPreviousRange(filters, current), filters.unit),
            });
        },
    });
}
