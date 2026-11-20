import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { DashboardFilters, DashboardPeriodUnit } from '../models/dashboard-filters.model';

@Injectable({ providedIn: 'root' })
export class DashboardApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getReport<T>(): Observable<T> {
        return this.http.get<T>(`${this.configService.apiUrl}dashboard/report/`);
    }

    getStats<T>(filters: DashboardFilters): Observable<T> {
        const { from, to } = toStatsRange(filters);
        const params = new HttpParams().set('from', from).set('to', to).set('group', filters.unit);
        return this.http.get<T>(`${this.configService.apiUrl}dashboard/stats/`, { params });
    }
}

function toStatsRange({ period, unit }: DashboardFilters): { from: string; to: string } {
    const now = new Date();
    const from = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
    if (unit === DashboardPeriodUnit.Day) from.setUTCDate(from.getUTCDate() - (period - 1));
    if (unit === DashboardPeriodUnit.Month) from.setUTCMonth(from.getUTCMonth() - (period - 1), 1);
    if (unit === DashboardPeriodUnit.Year) from.setUTCFullYear(from.getUTCFullYear() - (period - 1), 0, 1);
    return { from: toIsoDate(from), to: toIsoDate(now) };
}

function toIsoDate(date: Date): string {
    return date.toISOString().slice(0, 10);
}
