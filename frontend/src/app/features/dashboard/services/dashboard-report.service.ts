import { HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { catchError, Observable, of, throwError } from 'rxjs';

import { DashboardReport } from '../models/dashboard-report.model';
import { DashboardApiService } from './dashboard-api.service';
import { DashboardFiltersService } from './dashboard-filters.service';

@Injectable()
export class DashboardReportService {
    private readonly api = inject(DashboardApiService);
    private readonly filtersService = inject(DashboardFiltersService);

    readonly resource = rxResource({
        params: () => this.filtersService.refreshCount(),
        stream: () => this.api.getReport<DashboardReport>().pipe(catchError(nullWhenNotReady)),
    });

    readonly report = computed(() => (this.resource.hasValue() ? this.resource.value() : null));
}

function nullWhenNotReady(error: unknown): Observable<null> {
    const notReady =
        error instanceof HttpErrorResponse && error.status === 404 && error.error?.code === 'report_not_ready';
    return notReady ? of(null) : throwError(() => error);
}
