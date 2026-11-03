import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import { ToolFilterPreset, ToolFilterPresetCreate, ToolFilterPresetUpdate } from '../models/tool-filter-preset.model';

@Injectable({ providedIn: 'root' })
export class ToolFilterPresetsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}tool-filter-presets/`;
    }

    public getPresets(): Observable<ToolFilterPreset[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http
            .get<ApiGetRequest<ToolFilterPreset>>(this.baseUrl, { params })
            .pipe(map((page) => page.results));
    }

    public createPreset(payload: ToolFilterPresetCreate): Observable<ToolFilterPreset> {
        return this.http.post<ToolFilterPreset>(this.baseUrl, payload);
    }

    public updatePreset(id: number, changes: ToolFilterPresetUpdate): Observable<ToolFilterPreset> {
        return this.http.patch<ToolFilterPreset>(`${this.baseUrl}${id}/`, changes);
    }

    public deletePreset(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`);
    }
}
