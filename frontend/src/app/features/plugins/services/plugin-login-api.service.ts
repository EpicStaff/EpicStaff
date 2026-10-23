import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { PluginLoginOrganizations } from '../models/plugin-login.model';

@Injectable({ providedIn: 'root' })
export class PluginLoginApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    /**
     * `GET /api/plugins/{identifier}/login-organizations/`: the caller's own organizations where they may sign in to
     * the plugin. Not scoped to the active organization (the server ignores the organization header).
     */
    loginOrganizations(identifier: string): Observable<PluginLoginOrganizations> {
        return this.http.get<PluginLoginOrganizations>(
            `${this.configService.apiUrl}plugins/${encodeURIComponent(identifier)}/login-organizations/`
        );
    }
}
