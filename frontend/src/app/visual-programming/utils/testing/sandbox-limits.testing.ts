import { EnvironmentProviders, inject, provideEnvironmentInitializer } from '@angular/core';

import { SandboxLimitsStorageService } from '../../services/sandbox-limits-storage.service';

/** The sandbox ceiling in tests, in minutes. */
export const TEST_MAX_EXECUTION_TIMEOUT_MINUTES = 60;

/** Sandbox limits as the flow editor route's resolver leaves them: loaded before any panel opens. */
export function provideLoadedSandboxLimits(): EnvironmentProviders {
    return provideEnvironmentInitializer(() =>
        inject(SandboxLimitsStorageService).setLimits({
            max_execution_timeout_minutes: TEST_MAX_EXECUTION_TIMEOUT_MINUTES,
        })
    );
}
