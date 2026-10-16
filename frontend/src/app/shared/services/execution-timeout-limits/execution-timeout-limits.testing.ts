import { EnvironmentProviders, inject, makeEnvironmentProviders, provideEnvironmentInitializer } from '@angular/core';
import { ExecutionTimeoutLimits, GetExecutionTimeoutLimitsResponse } from '@shared/models';
import { of } from 'rxjs';

import { ExecutionTimeoutLimitsApiService } from './execution-timeout-limits-api.service';
import { ExecutionTimeoutLimitsStorageService } from './execution-timeout-limits-storage.service';

/** The execution timeout limits in tests, in seconds. */
export const TEST_EXECUTION_TIMEOUT_LIMITS: ExecutionTimeoutLimits = {
    minSeconds: 5,
    defaultSeconds: 120,
    maxSeconds: 3600,
};

/** The limits as the backend returns them. */
export function executionTimeoutLimitsResponse(
    limits: ExecutionTimeoutLimits = TEST_EXECUTION_TIMEOUT_LIMITS
): GetExecutionTimeoutLimitsResponse {
    return {
        min_seconds: limits.minSeconds,
        default_seconds: limits.defaultSeconds,
        max_seconds: limits.maxSeconds,
    };
}

/** The limits as the flow editor route's resolver leaves them: loaded before any screen reads them. */
export function provideLoadedExecutionTimeoutLimits(
    limits: ExecutionTimeoutLimits = TEST_EXECUTION_TIMEOUT_LIMITS
): EnvironmentProviders {
    const response = executionTimeoutLimitsResponse(limits);
    return makeEnvironmentProviders([
        { provide: ExecutionTimeoutLimitsApiService, useValue: { getExecutionTimeoutLimits: () => of(response) } },
        provideEnvironmentInitializer(() => {
            inject(ExecutionTimeoutLimitsStorageService).load().subscribe();
        }),
    ]);
}
