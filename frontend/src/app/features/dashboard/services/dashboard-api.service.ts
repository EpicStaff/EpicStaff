import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { DashboardPeriodUnit } from '../models/dashboard-filters.model';
import { DashboardRange, toIsoDate } from '../utils/dashboard-range.util';

@Injectable({ providedIn: 'root' })
export class DashboardApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getReport<T>(): Observable<T> {
        return this.http.get<T>(`${this.configService.apiUrl}dashboard/report/`);
    }

    getStats<T>({ from, to }: DashboardRange, group: DashboardPeriodUnit): Observable<T> {
        const params = new HttpParams().set('from', toIsoDate(from)).set('to', toIsoDate(to)).set('group', group);
        return this.http.get<T>(`${this.configService.apiUrl}dashboard/stats/`, { params });
    }
}
