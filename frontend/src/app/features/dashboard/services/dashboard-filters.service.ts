import { computed, inject, Injectable, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, ParamMap, Router } from '@angular/router';

import { DashboardFilters, DashboardPeriodUnit, DEFAULT_DASHBOARD_FILTERS } from '../models/dashboard-filters.model';

@Injectable()
export class DashboardFiltersService {
    private readonly router = inject(Router);
    private readonly queryParams = toSignal(inject(ActivatedRoute).queryParamMap, { requireSync: true });

    readonly filters = computed(() => parseFilters(this.queryParams()));
    readonly refreshCount = signal(0);

    setPeriod(period: number): void {
        this.update({ period });
    }

    setUnit(unit: DashboardPeriodUnit): void {
        this.update({ unit });
    }

    refresh(): void {
        this.refreshCount.update((count) => count + 1);
    }

    private update(changes: Partial<DashboardFilters>): void {
        const next = { ...this.filters(), ...changes };
        void this.router.navigate([], {
            queryParams: { period: next.period, unit: next.unit },
            queryParamsHandling: 'merge',
            replaceUrl: true,
        });
    }
}

function parseFilters(params: ParamMap): DashboardFilters {
    const unitParam = params.get('unit') as DashboardPeriodUnit;
    const period = Number(params.get('period'));
    return {
        period: Number.isInteger(period) && period >= 1 ? period : DEFAULT_DASHBOARD_FILTERS.period,
        unit: Object.values(DashboardPeriodUnit).includes(unitParam) ? unitParam : DEFAULT_DASHBOARD_FILTERS.unit,
    };
}
