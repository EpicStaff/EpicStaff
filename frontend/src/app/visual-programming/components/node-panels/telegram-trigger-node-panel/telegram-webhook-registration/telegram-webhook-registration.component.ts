import { DatePipe } from '@angular/common';
import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, input, linkedSignal, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { concat, defer, EMPTY, merge, Observable, of, Subject } from 'rxjs';
import { catchError, filter, map, pairwise, startWith, switchMap } from 'rxjs/operators';

import { FlowsApiService } from '../../../../../features/flows/services/flows-api.service';
import {
    TelegramRegistrationBlocker,
    TelegramRegistrationBlockerCode,
    TelegramWebhookInfo,
} from '../../../../core/models/telegram-trigger.model';
import { SidePanelService } from '../../../../services/side-panel.service';
import {
    TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE,
    TELEGRAM_BOT_KEY_REJECTED_CODE,
    TELEGRAM_REGISTRATION_BLOCKED_CODE,
    TELEGRAM_REGISTRATION_FAILED_CODE,
    TELEGRAM_TUNNEL_UNAVAILABLE_CODE,
    TELEGRAM_WEBHOOK_INFO_UNAVAILABLE_CODE,
    TelegramRegisterAttempt,
    TelegramWebhookCheck,
} from './telegram-webhook-check.model';

/**
 * What blocks registration, and how an editor fixes it. Read-only users see only `problem`: they
 * cannot pick or edit anything. Keyed on the full union, so a new code without copy fails the build.
 */
const BLOCKER_DESCRIPTIONS: Readonly<Record<TelegramRegistrationBlockerCode, { problem: string; fix: string }>> = {
    no_webhook_trigger: {
        problem: 'This node has no webhook trigger, so its webhook cannot be registered.',
        fix: 'Pick or create a webhook trigger above and save the flow.',
    },
    no_tunnel_provider: {
        problem: 'This webhook trigger has no tunnel provider, so Telegram has no public URL to deliver to.',
        fix: 'In Settings > Webhook Triggers, edit this trigger to use ngrok, then press Check.',
    },
    localhost_provider: {
        problem: 'This webhook trigger uses a localhost provider, which Telegram cannot reach.',
        fix: 'Pick or create an ngrok trigger above and save the flow.',
    },
    auth_kind_conflict: {
        problem: 'This webhook trigger already uses another kind of authentication, so it cannot be used for Telegram.',
        fix: 'Pick or create a different webhook trigger above and save the flow.',
    },
    no_telegram_secret: {
        problem: 'This webhook trigger has no Telegram secret, so its webhook cannot be registered.',
        fix: 'In Settings > Webhook Triggers, edit this trigger to add a Telegram secret, then press Check.',
    },
    invalid_telegram_secret: {
        problem:
            "This webhook trigger's Telegram secret is not in a format Telegram accepts, so its webhook cannot be registered.",
        fix: 'In Settings > Webhook Triggers, edit this trigger to use a different Telegram secret, then press Check.',
    },
    unresolvable_telegram_secret: {
        problem: "This webhook trigger's Telegram secret could not be read, so its webhook cannot be registered.",
        fix: 'In Settings > Webhook Triggers, edit this trigger to set its Telegram secret again, then press Check.',
    },
};

/** Fixed copy for a 422 `telegram_bot_key_rejected`, from Check and Register alike; never server text. */
const BOT_KEY_REJECTED_TEXT = 'Telegram rejected this bot key. Check the secret selected as the bot key on this node.';
const BOT_KEY_REJECTED_SUMMARY = 'Telegram rejected the bot key.';

function isKnownBlockerCode(code: string): code is TelegramRegistrationBlockerCode {
    return Object.hasOwn(BLOCKER_DESCRIPTIONS, code);
}

/** Our copy for a known code; the server's own message for a code this UI does not know yet. */
function describeBlocker(blocker: TelegramRegistrationBlocker, readonly: boolean): string {
    if (!isKnownBlockerCode(blocker.code)) return blocker.message;
    const { problem, fix } = BLOCKER_DESCRIPTIONS[blocker.code];
    return readonly ? problem : `${problem} ${fix}`;
}

function loaded(info: TelegramWebhookInfo, registerAttempt: TelegramRegisterAttempt = 'idle'): TelegramWebhookCheck {
    return { state: 'loaded', info, registerAttempt };
}

function errorCode(error: HttpErrorResponse): string | null {
    const body: unknown = error.error;
    if (typeof body !== 'object' || body === null || !('code' in body)) return null;
    return typeof body.code === 'string' ? body.code : null;
}

function registrationBlocker(error: HttpErrorResponse): TelegramRegistrationBlocker | null {
    const body: unknown = error.error;
    if (typeof body !== 'object' || body === null || !('registration_blocker' in body)) return null;
    const blocker: unknown = body.registration_blocker;
    if (typeof blocker !== 'object' || blocker === null || !('code' in blocker) || !('message' in blocker)) {
        return null;
    }
    if (typeof blocker.code !== 'string' || typeof blocker.message !== 'string') return null;
    return { code: blocker.code, message: blocker.message };
}

/** Maps the backend's `{ status_code, code, message }` error envelope to a check state. */
function toFailedCheck(error: unknown): TelegramWebhookCheck {
    if (!(error instanceof HttpErrorResponse)) return { state: 'error' };
    if (error.status === HttpStatusCode.BadGateway) return { state: 'telegram-unreachable' };
    if (isBotKeyRejected(error)) return { state: 'bot-key-rejected' };
    if (error.status === HttpStatusCode.BadRequest && errorCode(error) === TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE) {
        return { state: 'no-bot-key' };
    }
    return { state: 'error' };
}

/**
 * Maps a failed `register-webhook` call. The status shown before the attempt stays on screen: a
 * failure left Telegram unchanged, and after an unreadable success only Check can tell the truth.
 */
function toFailedRegistration(error: unknown, currentInfo: TelegramWebhookInfo): TelegramWebhookCheck {
    if (!(error instanceof HttpErrorResponse)) return loaded(currentInfo, 'failed-other');
    const code = errorCode(error);
    if (error.status === HttpStatusCode.Conflict && code === TELEGRAM_REGISTRATION_BLOCKED_CODE) {
        const blocker = registrationBlocker(error);
        if (blocker) return loaded({ ...currentInfo, registration_blocker: blocker }, 'blocked');
    }
    if (error.status === HttpStatusCode.BadRequest && code === TELEGRAM_BOT_KEY_NOT_CONFIGURED_CODE) {
        return { state: 'no-bot-key' };
    }
    if (error.status === HttpStatusCode.BadGateway && code === TELEGRAM_REGISTRATION_FAILED_CODE) {
        return loaded(currentInfo, 'failed-telegram');
    }
    if (error.status === HttpStatusCode.BadGateway && code === TELEGRAM_WEBHOOK_INFO_UNAVAILABLE_CODE) {
        return loaded(currentInfo, 'registered-unread');
    }
    if (error.status === HttpStatusCode.ServiceUnavailable && code === TELEGRAM_TUNNEL_UNAVAILABLE_CODE) {
        return loaded(currentInfo, 'failed-tunnel');
    }
    if (isBotKeyRejected(error)) return loaded(currentInfo, 'failed-bot-key-rejected');
    return loaded(currentInfo, 'failed-other');
}

/** Telegram answered 401/404 for the saved bot key (malformed, unknown or revoked token). */
function isBotKeyRejected(error: HttpErrorResponse): boolean {
    return error.status === HttpStatusCode.UnprocessableEntity && errorCode(error) === TELEGRAM_BOT_KEY_REJECTED_CODE;
}

/**
 * Shows which URL Telegram actually delivers to for the node's bot key, and lets the user point it
 * at this node with Register. Telegram keeps only the last `setWebhook` URL per bot, so two telegram
 * trigger nodes sharing one key silently steal each other's messages — this makes that visible. It
 * reads and registers the backend's saved state only, so the inputs must be the node's saved
 * values, not the live form or the in-memory canvas node.
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
    /** The user cannot change the flow: Register (an UPDATE) is hidden and blockers get no how-to. */
    readonly readonly = input<boolean>(false);

    protected readonly canCheck = computed(() => this.backendId() != null && this.botKeySecretId() != null);
    /** Before the first fetch emits, show what the inputs already imply instead of a placeholder. */
    protected readonly check = computed<TelegramWebhookCheck>(() => this.fetchedCheck() ?? this.checkWithoutFetch());
    protected readonly info = computed(() => {
        const check = this.check();
        return check.state === 'loaded' ? check.info : null;
    });
    protected readonly registerAttempt = computed<TelegramRegisterAttempt>(() => {
        const check = this.check();
        return check.state === 'loaded' ? check.registerAttempt : 'idle';
    });
    protected readonly isRegistering = computed(() => this.registerAttempt() === 'in-progress');
    protected readonly isBusy = computed(() => this.check().state === 'loading' || this.isRegistering());
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
    protected readonly isNotRegistered = computed(() => {
        const info = this.info();
        return info != null && info.registered_url == null;
    });
    protected readonly registrationBlocker = computed(() => this.info()?.registration_blocker ?? null);
    protected readonly blockerText = computed(() => {
        const blocker = this.registrationBlocker();
        return blocker ? describeBlocker(blocker, this.readonly()) : null;
    });
    /** Register helps only when Telegram is not delivering here and nothing blocks registration. */
    protected readonly showsRegister = computed(
        () => !this.readonly() && this.registrationBlocker() == null && (this.isNotRegistered() || this.isMismatch())
    );
    /** Register acts on the saved configuration, so it waits until connection edits are saved. */
    protected readonly canRegister = computed(
        () => this.showsRegister() && !this.hasUnsavedConnectionChanges() && !this.isBusy()
    );
    /**
     * A short summary for the live region, so a change is not announced as the whole panel. An
     * automatic refetch keeps the previous summary until its verdict is in, so an unchanged verdict
     * is not announced again; only a user's Check or Register announces that it is running.
     */
    protected readonly announcement = linkedSignal<TelegramWebhookCheck, string>({
        source: this.check,
        computation: (check, previous) => this.summarize(check) ?? previous?.value ?? '',
    });

    protected readonly botKeyRejectedText = BOT_KEY_REJECTED_TEXT;

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
    private readonly registerRequests = new Subject<void>();
    /** A save or input change arrived while Register was in flight; fetch once it has finished. */
    private refetchAfterRegister = false;

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
        const automaticFetch$ = merge(
            toObservable(this.savedConnection),
            this.sidePanelService.graphSaved$,
            thisNodeSaveFinished$
        ).pipe(map(() => false));
        const fetch$ = merge(automaticFetch$, this.manualCheckRequests.pipe(map(() => true))).pipe(
            // switchMap below would cancel the POST, and its result would never be shown.
            filter(() => !this.deferWhileRegistering()),
            map((requestedByUser) => () => this.fetchRegistration(requestedByUser))
        );
        // canRegister is false while a check or a register runs, which drops double clicks.
        const register$ = this.registerRequests.pipe(
            filter(() => this.canRegister()),
            map(() => () => this.registerThenCatchUp())
        );

        // Checks replace each other (the newest one wins); a running register is never replaced.
        merge(fetch$, register$)
            .pipe(
                switchMap((request) => request()),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((check) => this.fetchedCheck.set(check));
    }

    protected refresh(): void {
        this.manualCheckRequests.next();
    }

    protected registerWebhook(): void {
        this.registerRequests.next();
    }

    /** True, and remembers to fetch afterwards, when a register request is in flight. */
    private deferWhileRegistering(): boolean {
        if (!this.isRegistering()) return false;
        this.refetchAfterRegister = true;
        return true;
    }

    private fetchRegistration(requestedByUser: boolean): Observable<TelegramWebhookCheck> {
        const backendId = this.backendId();
        if (backendId == null || !this.canCheck()) return of(this.checkWithoutFetch());

        return this.flowsApiService.getTelegramTriggerWebhookInfo(backendId).pipe(
            map((info): TelegramWebhookCheck => loaded(info)),
            catchError((error: unknown) => of(toFailedCheck(error))),
            startWith<TelegramWebhookCheck>({ state: 'loading', requestedByUser })
        );
    }

    /** Registers, then runs one automatic fetch if a save or input change came in meanwhile. */
    private registerThenCatchUp(): Observable<TelegramWebhookCheck> {
        this.refetchAfterRegister = false;
        return concat(
            this.register(),
            defer(() => (this.refetchAfterRegister ? this.fetchRegistration(false) : EMPTY))
        );
    }

    /** Keeps the current status on screen while registering and after a failed attempt. */
    private register(): Observable<TelegramWebhookCheck> {
        const backendId = this.backendId();
        const currentInfo = this.info();
        if (backendId == null || currentInfo == null) return EMPTY;

        return this.flowsApiService.registerTelegramTriggerWebhook(backendId).pipe(
            map((freshInfo): TelegramWebhookCheck => loaded(freshInfo)),
            catchError((error: unknown) => of(toFailedRegistration(error, currentInfo))),
            startWith<TelegramWebhookCheck>(loaded(currentInfo, 'in-progress'))
        );
    }

    /** The state the inputs imply on their own: why no check can run, or that one is starting. */
    private checkWithoutFetch(): TelegramWebhookCheck {
        if (this.backendId() == null) return { state: 'not-saved' };
        if (this.botKeySecretId() == null) return { state: 'no-bot-key' };
        return { state: 'loading', requestedByUser: false };
    }

    /** null: nothing new to say, keep the previous summary. */
    private summarize(check: TelegramWebhookCheck): string | null {
        switch (check.state) {
            case 'not-saved':
            case 'no-bot-key':
                return '';
            case 'loading':
                return check.requestedByUser ? 'Checking Telegram…' : null;
            case 'telegram-unreachable':
            case 'error':
                return "Couldn't check the registration.";
            case 'bot-key-rejected':
                return BOT_KEY_REJECTED_SUMMARY;
            case 'loaded':
                return this.summarizeLoaded(check.info, check.registerAttempt);
        }
    }

    private summarizeLoaded(info: TelegramWebhookInfo, registerAttempt: TelegramRegisterAttempt): string {
        switch (registerAttempt) {
            case 'in-progress':
                return 'Registering the webhook…';
            case 'registered-unread':
                return 'Registered, but the status could not be read back.';
            case 'failed-bot-key-rejected':
                return BOT_KEY_REJECTED_SUMMARY;
            case 'failed-telegram':
            case 'failed-tunnel':
            case 'failed-other':
                return "Couldn't register the webhook.";
            case 'idle':
            case 'blocked':
                break;
        }
        if (info.registration_blocker) return 'The webhook cannot be registered.';
        if (info.is_match === true) return 'Telegram is delivering to this trigger.';
        if (info.registered_url == null) return 'No webhook registered for this bot key.';
        if (info.is_match === false) return 'This bot key is registered to a different URL.';
        return 'Webhook registration checked.';
    }
}
