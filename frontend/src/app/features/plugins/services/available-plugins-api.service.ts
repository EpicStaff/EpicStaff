import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { AvailablePlugin } from '../models/available-plugin.model';

@Injectable({ providedIn: 'root' })
export class AvailablePluginsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    /** `GET /api/plugins/available/` for the active organization (the org interceptor adds its header). */
    list(): Observable<AvailablePlugin[]> {
        return this.http.get<AvailablePlugin[]>(`${this.configService.apiUrl}plugins/available/`);
    }
}
