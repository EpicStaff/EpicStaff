import { computed, DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActionCode, ResourceCode } from '@shared/models';
import { Subject, throttleTime } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';

/**
 * Exposes whether the current user has read-only access to flows (Flows:Read
 * without Flows:Update) and provides a throttled toast for blocked write
 * interactions in the visual-programming editor.
 */
@Injectable({ providedIn: 'root' })
export class FlowReadOnlyService {
    private readonly perms = inject(PermissionsService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isReadOnly = computed(() => !this.perms.can(ResourceCode.Flows, ActionCode.Update));

    private readonly blocked$ = new Subject<void>();

    constructor() {
        this.blocked$.pipe(throttleTime(3000), takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.toast.info('You have read-only access to this flow.');
        });
    }

    /** Show the "read-only access" toast, throttled to at most once per 3 seconds. */
    public notifyBlocked(): void {
        this.blocked$.next();
    }
}
