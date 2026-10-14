import { computed, DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import { Subject, throttleTime } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { isTriggerNodeType } from '../core/helpers/trigger-node-type.util';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';

export const TRIGGER_NODES_NEED_RUN_MESSAGE =
    'Adding or changing trigger nodes (Webhook, Telegram, Schedule) needs the Run permission on flows.';

/**
 * Whether the visual-programming editor may change the flow: not for a user with Flows:Read
 * without Flows:Update, and never inside a version preview. Trigger nodes also need Flows:Run.
 * Also owns the throttled messages shown when a write interaction is blocked.
 *
 * `providedIn: 'root'` for the live editor; the version preview gets its own instance through
 * FLOW_EDITOR_STATE_PROVIDERS, next to its FLOW_EDITOR_PREVIEW = true.
 */
@Injectable({ providedIn: 'root' })
export class FlowReadOnlyService {
    public readonly isPreview = inject(FLOW_EDITOR_PREVIEW);

    private readonly perms = inject(PermissionsService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isReadOnly = computed(
        () => this.isPreview || !this.perms.can(ResourceCode.Flows, ActionCode.Update)
    );

    /**
     * A trigger node starts flow runs on its own, so creating or changing one (its fields, but also
     * its position) needs Flows:Run on top of an editable flow. Deleting one does not.
     */
    public readonly canEditTriggerNodes = computed(
        () => !this.isReadOnly() && this.perms.can(ResourceCode.Flows, ActionCode.Run)
    );

    private readonly blocked$ = new Subject<void>();
    private readonly triggerNodesBlocked$ = new Subject<void>();

    constructor() {
        this.blocked$.pipe(throttleTime(3000), takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            if (this.isPreview) {
                this.toast.info('Preview mode is read-only. Exit preview to edit the flow', 3000, 'bottom-right');
                return;
            }
            this.toast.info('You have read-only access to this flow.');
        });
        this.triggerNodesBlocked$
            .pipe(throttleTime(3000), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.toast.info(TRIGGER_NODES_NEED_RUN_MESSAGE));
    }

    /** Whether a node of this type may not be created or changed in this editor. */
    public isNodeTypeReadOnly(type: NodeType): boolean {
        return this.isReadOnly() || (isTriggerNodeType(type) && !this.canEditTriggerNodes());
    }

    /** Say why a write interaction was blocked, at most once per 3 seconds. */
    public notifyBlocked(): void {
        this.blocked$.next();
    }

    /** Say why a node of this type could not be created or changed, at most once per 3 seconds per reason. */
    public notifyNodeTypeBlocked(type: NodeType): void {
        if (this.isReadOnly()) {
            this.notifyBlocked();
        } else if (this.isNodeTypeReadOnly(type)) {
            this.triggerNodesBlocked$.next();
        }
    }
}
