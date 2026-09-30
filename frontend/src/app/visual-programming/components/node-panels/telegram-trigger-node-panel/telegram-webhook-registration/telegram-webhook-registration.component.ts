import { DatePipe } from '@angular/common';
import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { merge, Observable, of, Subject } from 'rxjs';
import { catchError, filter, map, pairwise, startWith, switchMap } from 'rxjs/operators';

import { FlowsApiService } from '../../../../../features/flows/services/flows-api.service';
import { SidePanelService } from '../../../../services/side-panel.service';
import { TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE, TelegramWebhookCheck } from './telegram-webhook-check.model';

/**
 * Shows which URL Telegram actually delivers to for the node's bot key. Telegram keeps only the
 * last `setWebhook` URL per bot, so two telegram trigger nodes sharing one key silently steal each
 * other's messages — this makes that visible. It reads the backend's saved state only, so the
 * inputs must be the node's saved values, not the live form or the in-memory canvas node.
 */
@Component({
    selector: 'app-telegram-webhook-registration',
    imports: [AppSvgIconComponent, ButtonComponent, DatePipe],
    templateUrl: './telegram-webhook-registration.component.html',
    styleUrls: ['./telegram-webhook-registration.component.scss'],
})
export class TelegramWebhookRegistrationComponent {
    /** Canvas id of the node; a finished single-node save refetches only when it was this node's. */
    readonly nodeId = input.required<string>();
    readonly backendId = input<number | null>(null);
    readonly botKeySecretId = input<number | null>(null);
    /** The panel form has a bot key or webhook trigger that is not saved yet. */
    readonly hasUnsavedConnectionChanges = input<boolean>(false);

    protected readonly canCheck = computed(() => this.backendId() != null && this.botKeySecretId() != null);
    /** Before the first fetch emits, show what the inputs already imply instead of a placeholder. */
    protected readonly check = computed<TelegramWebhookCheck>(() => this.fetchedCheck() ?? this.checkWithoutFetch());
    protected readonly isLoading = computed(() => this.check().state === 'loading');
    protected readonly info = computed(() => {
        const check = this.check();
        return check.state === 'loaded' ? check.info : null;
    });
    protected readonly isMatch = computed(() => this.info()?.is_match === true);
    /** `is_match` is also false when nothing is registered; only a different registered URL is a mismatch. */
    protected readonly isMismatch = computed(() => {
        const info = this.info();
        return info?.registered_url != null && info.is_match === false;
    });
    /** A URL is registered but this trigger's own URL is unknown, so the two cannot be compared. */
    protected readonly isUncomparable = computed(() => {
        const info = this.info();
        return info?.registered_url != null && info.is_match === null;
    });
    private readonly fetchedCheck = signal<TelegramWebhookCheck | null>(null);
    private readonly savedConnection = computed(
        () => ({ backendId: this.backendId(), botKeySecretId: this.botKeySecretId() }),
        {
            equal: (previous, next) =>
                previous.backendId === next.backendId && previous.botKeySecretId === next.botKeySecretId,
        }
    );

    private readonly flowsApiService = inject(FlowsApiService);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly manualCheckRequests = new Subject<void>();

    constructor() {
        // A newly saved node gets its backendId through the input one change-detection pass after
        // graphSaved$ fires, so the input change triggers the fetch. graphSaved$ and a finished
        // single-node save of this node cover re-saves of an existing node, where Telegram may
        // have been re-registered without any input changing (a single-node save does not emit
        // graphSaved$).
        const thisNodeSaveFinished$ = toObservable(this.sidePanelService.savingNodeId).pipe(
            pairwise(),
            filter(
                ([previousSavingNodeId, savingNodeId]) => previousSavingNodeId === this.nodeId() && savingNodeId == null
            )
        );
        merge(
            toObservable(this.savedConnection),
            this.sidePanelService.graphSaved$,
            thisNodeSaveFinished$,
            this.manualCheckRequests
        )
            .pipe(
                switchMap(() => this.fetchRegistration()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((check) => this.fetchedCheck.set(check));
    }

    protected refresh(): void {
        this.manualCheckRequests.next();
    }

    private fetchRegistration(): Observable<TelegramWebhookCheck> {
        const backendId = this.backendId();
        if (backendId == null || !this.canCheck()) return of(this.checkWithoutFetch());

        return this.flowsApiService.getTelegramTriggerWebhookInfo(backendId).pipe(
            map((info): TelegramWebhookCheck => ({ state: 'loaded', info })),
            catchError((error: unknown) => of(toFailedCheck(error))),
            startWith<TelegramWebhookCheck>({ state: 'loading' })
        );
    }

    /** The state the inputs imply on their own: why no check can run, or that one is starting. */
    private checkWithoutFetch(): TelegramWebhookCheck {
        if (this.backendId() == null) return { state: 'not-saved' };
        if (this.botKeySecretId() == null) return { state: 'no-bot-key' };
        return { state: 'loading' };
    }
}

/** Maps the backend's `{ status_code, code, message }` error envelope to a check state. */
function toFailedCheck(error: unknown): TelegramWebhookCheck {
    if (!(error instanceof HttpErrorResponse)) return { state: 'error' };
    if (error.status === HttpStatusCode.BadGateway) return { state: 'telegram-unreachable' };
    if (error.status === HttpStatusCode.BadRequest && errorCode(error) === TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE) {
        return { state: 'no-bot-key' };
    }
    return { state: 'error' };
}

function errorCode(error: HttpErrorResponse): string | null {
    const body: unknown = error.error;
    if (typeof body !== 'object' || body === null || !('code' in body)) return null;
    return typeof body.code === 'string' ? body.code : null;
}
