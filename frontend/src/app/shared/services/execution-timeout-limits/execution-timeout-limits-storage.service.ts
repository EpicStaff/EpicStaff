import { inject, Injectable, signal, untracked } from '@angular/core';
import { ExecutionTimeoutLimits } from '@shared/models';
import { map, Observable, of, tap } from 'rxjs';

import { StorageService } from '../storage-service.interface';
import { ExecutionTimeoutLimitsApiService } from './execution-timeout-limits-api.service';

/**
 * The execution timeout limits, loaded once per session. A screen that edits python code loads them before it reads
 * them: the flow editor route resolves them (`executionTimeoutLimitsResolver`) before the editor opens, so everything
 * inside the editor may read them synchronously; the custom tool dialog loads them itself, as it opens from many screens.
 */
@Injectable({ providedIn: 'root' })
export class ExecutionTimeoutLimitsStorageService implements StorageService {
    private readonly executionTimeoutLimitsApiService = inject(ExecutionTimeoutLimitsApiService);
    private readonly limitsSignal = signal<ExecutionTimeoutLimits | null>(null);

    public load(): Observable<ExecutionTimeoutLimits> {
        const loaded = this.limitsSignal();
        if (loaded) return of(loaded);
        return this.executionTimeoutLimitsApiService.getExecutionTimeoutLimits().pipe(
            map(
                (response): ExecutionTimeoutLimits => ({
                    minSeconds: response.min_seconds,
                    defaultSeconds: response.default_seconds,
                    maxSeconds: response.max_seconds,
                })
            ),
            tap((limits) => this.limitsSignal.set(limits))
        );
    }

    /**
     * The loaded limits. Reading them before they are loaded is a wiring error (a screen that edits python code
     * without loading them first), so it throws instead of guessing.
     *
     * A one-off read that never makes its caller depend on the limits: a node panel reads them while its form is
     * built inside an effect, which must not run again (and throw) when a logout or an organization switch
     * clears every storage.
     */
    public limits(): ExecutionTimeoutLimits {
        const limits = untracked(this.limitsSignal);
        if (!limits) {
            throw new Error('Execution timeout limits are not loaded: load them before reading them.');
        }
        return limits;
    }

    /**
     * The timeout, in seconds, a python code stored with `storedSeconds` runs with: the backend gives a code
     * without one its default, and caps a longer one at the maximum.
     */
    public secondsToRun(storedSeconds: number | undefined): number {
        const { defaultSeconds, maxSeconds } = this.limits();
        const seconds = storedSeconds ?? defaultSeconds;
        return maxSeconds === null ? seconds : Math.min(seconds, maxSeconds);
    }

    public clear(): void {
        this.limitsSignal.set(null);
    }
}
