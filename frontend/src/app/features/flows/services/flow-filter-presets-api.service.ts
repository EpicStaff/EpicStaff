import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import { FlowFilterPreset, FlowFilterPresetCreate, FlowFilterPresetUpdate } from '../models/flow-filter-preset.model';

@Injectable({ providedIn: 'root' })
export class FlowFilterPresetsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}flow-filter-presets/`;
    }

    public getPresets(): Observable<FlowFilterPreset[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<FlowFilterPreset>>(this.baseUrl, { params })
            .pipe(map((page) => page.results));
    }

    public createPreset(payload: FlowFilterPresetCreate): Observable<FlowFilterPreset> {
        return this.http.post<FlowFilterPreset>(this.baseUrl, payload);
    }

    public updatePreset(id: number, changes: FlowFilterPresetUpdate): Observable<FlowFilterPreset> {
        return this.http.patch<FlowFilterPreset>(`${this.baseUrl}${id}/`, changes);
    }

    public deletePreset(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`);
    }
}
