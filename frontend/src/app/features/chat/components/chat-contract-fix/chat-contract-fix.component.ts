import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { ButtonComponent, HintMessageComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { extractHttpErrorMessage } from '@shared/utils';
import { map, of, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import { ChatContractMissing } from '../../models/chat.model';
import {
    CHAT_END_OUTPUT_NAMES,
    CHAT_START_VARIABLE_NAMES,
    contractFixPayload,
    isAutoFixable,
} from '../../utils/contract-fix.util';

let nextPanelId = 0;

/**
 * What a flow lacks for the chat contract, and the fix: adds the chat variables to the start node's Domain and the
 * chat outputs to the end node, where missing, and saves the flow. A flow without a start or end node is fixed in the
 * flow editor instead. Emits `applied` once the flow is saved (or found fixed), for the contract to be checked again.
 */
@Component({
    selector: 'app-chat-contract-fix',
    imports: [RouterLink, MatTooltip, ButtonComponent, HintMessageComponent],
    templateUrl: './chat-contract-fix.component.html',
    styleUrls: ['./chat-contract-fix.component.scss'],
})
export class ChatContractFixComponent {
    readonly graphId = input.required<number>();
    readonly missing = input.required<ChatContractMissing>();
    readonly applied = output<void>();

    protected readonly isApplying = signal(false);
    protected readonly canEditFlow = computed(() => this.permissionsService.can(ResourceCode.Flows, ActionCode.Update));
    protected readonly canReadFlows = computed(() => this.permissionsService.can(ResourceCode.Flows, ActionCode.Read));
    protected readonly isFixable = computed(() => isAutoFixable(this.missing()));

    protected readonly startVariableNames = CHAT_START_VARIABLE_NAMES.join(', ');
    protected readonly endOutputNames = CHAT_END_OUTPUT_NAMES.join(', ');
    protected readonly titleId = `chat-contract-fix-${nextPanelId++}`;

    private readonly permissionsService = inject(PermissionsService);
    private readonly flowsApi = inject(FlowsApiService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    protected apply(): void {
        if (this.isApplying()) return;
        const graphId = this.graphId();
        this.isApplying.set(true);
        this.flowsApi
            .getGraphById(graphId, true)
            .pipe(
                switchMap((graph) => {
                    const payload = contractFixPayload(graph);
                    // Nothing left to add: someone fixed the flow since the check.
                    return payload ? this.flowsApi.bulkSaveGraph(graphId, payload).pipe(map(() => true)) : of(false);
                }),
                // shortcut: picking another flow or closing the dialog mid-apply drops the toast of a save that may
                // have gone through, move the apply to a service that outlives the panel if users report it.
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (saved) => {
                    this.isApplying.set(false);
                    if (saved) this.toastService.success('Flow updated for chat');
                    else this.toastService.info('The flow already meets the chat contract');
                    this.applied.emit();
                },
                error: (error: HttpErrorResponse) => {
                    this.isApplying.set(false);
                    if (error.status === 409) {
                        this.toastService.warning('The flow changed meanwhile. Apply the fix again.');
                        return;
                    }
                    this.toastService.error(`Failed to update the flow: ${extractHttpErrorMessage(error)}`);
                },
            });
    }
}
