import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { GetExecutionTimeoutLimitsResponse } from '@shared/models';
import { Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';

@Injectable({ providedIn: 'root' })
export class ExecutionTimeoutLimitsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getExecutionTimeoutLimits(): Observable<GetExecutionTimeoutLimitsResponse> {
        return this.http.get<GetExecutionTimeoutLimitsResponse>(
            `${this.configService.apiUrl}execution-timeout-limits/`
        );
    }
}
