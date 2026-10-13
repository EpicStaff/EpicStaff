import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { Observable, of, tap } from 'rxjs';

import { GetSandboxLimitsResponse } from '../core/models/sandbox-limits.model';
import { SandboxLimitsApiService } from './sandbox-limits-api.service';

/**
 * The sandbox limits, loaded once per session. The flow editor route resolves them (`sandboxLimitsResolver`)
 * before the editor opens, so everything inside the editor may read them synchronously.
 */
@Injectable({ providedIn: 'root' })
export class SandboxLimitsStorageService implements StorageService {
    private readonly sandboxLimitsApiService = inject(SandboxLimitsApiService);
    private readonly limitsSignal = signal<GetSandboxLimitsResponse | null>(null);

    public readonly limits = this.limitsSignal.asReadonly();

    public load(): Observable<GetSandboxLimitsResponse> {
        const loaded = this.limitsSignal();
        if (loaded) return of(loaded);
        return this.sandboxLimitsApiService.getSandboxLimits().pipe(tap((limits) => this.setLimits(limits)));
    }

    public setLimits(limits: GetSandboxLimitsResponse): void {
        this.limitsSignal.set(limits);
    }

    /**
     * The longest execution timeout a node may set, in minutes. Reading it before the limits are loaded is a
     * wiring error (a screen that edits nodes without the flow editor route's resolver), so it throws instead
     * of guessing a value the backend would reject.
     */
    public maxExecutionTimeoutMinutes(): number {
        const limits = this.limitsSignal();
        if (!limits) {
            throw new Error('Sandbox limits are not loaded: resolve them with sandboxLimitsResolver first.');
        }
        return limits.max_execution_timeout_minutes;
    }

    public clear(): void {
        this.limitsSignal.set(null);
    }
}
