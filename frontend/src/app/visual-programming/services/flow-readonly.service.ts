import { computed, inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';

/**
 * Exposes whether the current user has read-only access to flows (Flows:Read
 * without Flows:Update) and provides a single-shot toast for blocked write
 * interactions in the visual-programming editor.
 */
@Injectable({ providedIn: 'root' })
export class FlowReadOnlyService {
    private readonly perms = inject(PermissionsService);
    private readonly toast = inject(ToastService);

    public readonly isReadOnly = computed(() => !this.perms.can(ResourceCode.Flows, ActionCode.Update));

    private hasNotified = false;

    /** Show the "read-only access" toast once per session-lived instance. */
    public notifyBlocked(): void {
        if (this.hasNotified) return;
        this.hasNotified = true;
        this.toast.info('You have read-only access to this flow.');
    }
}
