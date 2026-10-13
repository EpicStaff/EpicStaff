import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { ConfigService } from '../../services/config';
import { GetSandboxLimitsResponse } from '../core/models/sandbox-limits.model';

@Injectable({ providedIn: 'root' })
export class SandboxLimitsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getSandboxLimits(): Observable<GetSandboxLimitsResponse> {
        return this.http.get<GetSandboxLimitsResponse>(`${this.configService.apiUrl}sandbox-limits/`);
    }
}
