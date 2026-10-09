import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../config';

export interface GetRecycleBinSettingsResponse {
    retention_days: number;
}

@Injectable({ providedIn: 'root' })
export class RecycleBinSettingsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getSettings(): Observable<GetRecycleBinSettingsResponse> {
        return this.http.get<GetRecycleBinSettingsResponse>(`${this.configService.apiUrl}recycle-bin/settings/`);
    }
}
