import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    WebhookTriggerFieldComponent,
} from '@shared/components';
import { SecretsStorageService, WebhookTriggerService } from '@shared/services';
import { extractHttpErrorMessage } from '@shared/utils';
import { Observable, of, switchMap } from 'rxjs';

import { RealtimeChannel, TwilioChannel } from '../../../../../shared/models/realtime-voice/realtime-channel.model';
import { RealtimeChannelService, TwilioPhoneNumber } from '../../../../../shared/services/realtime-channel.service';
import {
    WebhookTriggerModel,
    WebhookTriggerWrite,
} from '../../../../../visual-programming/core/models/webhook-trigger.model';
import { AgentDefinition } from '../../../../agent-definitions/models/agent-definition.model';
import { AgentDefinitionsApiService } from '../../../../agent-definitions/services/agent-definitions-api.service';

export interface AddEditChannelDialogData {
    channel: RealtimeChannel | null;
    action: 'create' | 'update';
}

@Component({
    selector: 'app-add-edit-channel-dialog',
    templateUrl: './add-edit-channel-dialog.component.html',
    styleUrls: ['./add-edit-channel-dialog.component.scss'],
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        SelectComponent,
        ButtonComponent,
        WebhookTriggerFieldComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddEditChannelDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef);
    private channelService = inject(RealtimeChannelService);
    private agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private webhookTriggerService = inject(WebhookTriggerService);
    private secretsStorageService = inject(SecretsStorageService);
    private destroyRef = inject(DestroyRef);

    data: AddEditChannelDialogData = inject(DIALOG_DATA);

    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);

    private savedChannel = signal<RealtimeChannel | null>(this.data.channel);
    /** The trigger model resolved by the field (picked existing, or inline draft). */
    private resolvedTrigger = signal<WebhookTriggerModel | null>(this.data.channel?.twilio?.webhook_trigger ?? null);
    /** Id of a trigger we created during this dialog session, so retries update instead of duplicating. */
    private createdTriggerId = signal<number | null>(null);

    private agents = signal<AgentDefinition[]>([]);
    private phoneNumbers = signal<TwilioPhoneNumber[]>([]);
    private phonesFetched = signal<boolean>(false);
    phoneNumbersLoading = signal<boolean>(false);
    phoneLoadError = signal<string | null>(null);

    private readonly PHONE_CACHE_KEY = 'twilio_phone_numbers_cache_v2';

    agentItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.agents().map((a) => ({ name: a.name, value: a.id })),
    ]);

    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    phoneNumberItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.phoneNumbers().map((p) => ({
            name: p.friendly_name ? `${p.friendly_name} (${p.phone_number})` : p.phone_number,
            value: p.phone_number,
        })),
    ]);

    form!: FormGroup;

    ngOnInit(): void {
        const ch = this.data.channel;
        const tw = ch?.twilio;

        this.form = this.fb.group({
            name: [ch?.name ?? '', Validators.required],
            realtime_agent_definition: [ch?.realtime_agent_definition ?? null],
            is_active: [ch?.is_active ?? true],
            account_sid: [tw?.account_sid ?? '', Validators.required],
            auth_token_secret_id: [tw?.auth_token_secret_id ?? null, [Validators.required]],
            phone_number: [tw?.phone_number ?? ''],
            webhook_trigger: [(tw?.webhook_trigger?.id ?? null) as WebhookTriggerWrite | null],
        });

        // No server-side filter for this — the flag comes inline on the read model.
        this.agentDefinitionsApi
            .getAgentDefinitions()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (agents) =>
                    this.agents.set(agents.filter((a) => a.agent_definition_realtime_config_id != null)),
                error: () => {},
            });

        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });

        this.form
            .get('account_sid')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.resetPhoneNumbers());

        this.form
            .get('auth_token_secret_id')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.resetPhoneNumbers());

        if (ch?.id && tw?.account_sid && tw?.auth_token_secret_id != null && tw?.phone_number) {
            this.fetchPhoneNumbers();
        }

        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if ((event.ctrlKey || event.metaKey) && event.code === 'KeyS') {
                event.preventDefault();
                this.onSubmit();
            }
        });
    }

    onTriggerResolved(trigger: WebhookTriggerModel | null): void {
        this.resolvedTrigger.set(trigger);
    }

    onSubmit(): void {
        if (this.form.invalid) {
            this.form.markAllAsTouched();
            return;
        }
        this.isSubmitting.set(true);
        this.errorMessage.set(null);

        const v = this.form.value;
        const saved = this.savedChannel();

        if (!saved) {
            this.channelService
                .createChannel({
                    name: v.name,
                    channel_type: 'twilio',
                    realtime_agent_definition: v.realtime_agent_definition ?? null,
                    is_active: v.is_active,
                })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (channel) => {
                        this.savedChannel.set(channel);
                        this.channelService.channelsChanged$.next();
                        this.saveTwilioChannel(
                            channel.id,
                            channel.token,
                            v.account_sid,
                            v.auth_token_secret_id,
                            v.phone_number,
                            channel.twilio ?? null
                        );
                    },
                    error: (err: HttpErrorResponse) => {
                        this.errorMessage.set(this.formatBackendError(err) ?? 'Failed to create channel.');
                        this.isSubmitting.set(false);
                    },
                });
        } else {
            this.channelService
                .updateChannel({
                    id: saved.id,
                    name: v.name,
                    realtime_agent_definition: v.realtime_agent_definition ?? null,
                    is_active: v.is_active,
                })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.savedChannel.set({
                            ...saved,
                            name: v.name,
                            realtime_agent_definition: v.realtime_agent_definition ?? null,
                            is_active: v.is_active,
                        });
                        this.channelService.channelsChanged$.next();
                        this.saveTwilioChannel(
                            saved.id,
                            saved.token,
                            v.account_sid,
                            v.auth_token_secret_id,
                            v.phone_number,
                            saved.twilio ?? null
                        );
                    },
                    error: (err: HttpErrorResponse) => {
                        this.errorMessage.set(this.formatBackendError(err) ?? 'Failed to update channel.');
                        this.isSubmitting.set(false);
                    },
                });
        }
    }

    private saveTwilioChannel(
        channelId: number,
        channelToken: string,
        accountSid: string,
        authTokenSecretId: number | null,
        phoneNumber: string,
        existingTwilio: TwilioChannel | null
    ): void {
        const hasTwilioData = accountSid || authTokenSecretId != null || phoneNumber;

        if (!hasTwilioData) {
            this.dialogRef.close(true);
            return;
        }

        const currentTwilio = this.savedChannel()?.twilio ?? existingTwilio;

        // Resolve the webhook trigger first (write = int PK on TwilioChannel), then attach its id.
        this.resolveWebhookTrigger()
            .pipe(
                switchMap((trigger) => {
                    if (trigger?.id) {
                        this.createdTriggerId.set(trigger.id);
                        this.resolvedTrigger.set(trigger);
                    }
                    const webhookTriggerId = trigger?.id ?? null;
                    const obs = currentTwilio
                        ? this.channelService.updateTwilioChannel({
                              channel: currentTwilio.channel,
                              account_sid: accountSid,
                              auth_token_secret_id: authTokenSecretId,
                              phone_number: phoneNumber || null,
                              webhook_trigger: webhookTriggerId,
                          })
                        : this.channelService.createTwilioChannel({
                              channel: channelId,
                              account_sid: accountSid,
                              auth_token_secret_id: authTokenSecretId,
                              phone_number: phoneNumber || null,
                              webhook_trigger: webhookTriggerId,
                          });
                    return obs.pipe(switchMap((twilio) => of({ twilio, trigger })));
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: ({ twilio, trigger }) => {
                    const cur = this.savedChannel();
                    if (cur) this.savedChannel.set({ ...cur, twilio });
                    this.channelService.channelsChanged$.next();
                    this.configureWebhookAndClose(channelToken, phoneNumber, trigger);
                },
                error: (err: HttpErrorResponse) => {
                    this.errorMessage.set(
                        this.formatBackendError(err) ?? 'Channel saved but Twilio settings failed to save.'
                    );
                    this.isSubmitting.set(false);
                },
            });
    }

    /**
     * Resolve the chosen webhook trigger to a persisted model:
     * - `null` → no tunnel.
     * - `number` → existing trigger referenced by id (already loaded by the field, else fetch).
     * - object → inline create/update.
     */
    private resolveWebhookTrigger(): Observable<WebhookTriggerModel | null> {
        const value = this.form.value.webhook_trigger as WebhookTriggerWrite | null;
        if (value == null) return of(null);
        if (typeof value === 'number') {
            const resolved = this.resolvedTrigger();
            return resolved && resolved.id === value ? of(resolved) : this.webhookTriggerService.getById(value);
        }
        const existingId = value.id ?? this.createdTriggerId();
        return existingId
            ? this.webhookTriggerService.update(existingId, { ...value, id: existingId })
            : this.webhookTriggerService.create(value);
    }

    private configureWebhookAndClose(
        channelToken: string,
        phoneNumber: string,
        trigger: WebhookTriggerModel | null
    ): void {
        if (!phoneNumber || !trigger) {
            this.dialogRef.close(true);
            return;
        }

        const phoneSid = this.phoneNumbers().find((p) => p.phone_number === phoneNumber)?.sid;
        if (!phoneSid) {
            this.dialogRef.close(true);
            return;
        }

        this.channelService
            .configureWebhook(phoneSid, channelToken)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.dialogRef.close(true),
                error: (err: HttpErrorResponse) => {
                    this.errorMessage.set(
                        this.formatBackendError(err) ??
                            'Channel saved but webhook configuration on Twilio failed. Check your tunnel.'
                    );
                    this.isSubmitting.set(false);
                },
            });
    }

    private formatBackendError(err: HttpErrorResponse): string | null {
        const body = err?.error;
        if (!body) return null;
        if (typeof body === 'string') return body;
        if (typeof body.detail === 'string') return body.detail;
        if (typeof body === 'object') {
            const parts: string[] = [];
            for (const [field, value] of Object.entries(body)) {
                const text = Array.isArray(value) ? value.join(' ') : typeof value === 'string' ? value : null;
                if (text) parts.push(field === 'non_field_errors' ? text : `${field}: ${text}`);
            }
            if (parts.length) return parts.join(' • ');
        }
        return null;
    }

    onPhoneSelectOpened(): void {
        if (this.phoneNumberSelectDisabled()) return;
        if (this.phoneNumbersLoading() || this.phonesFetched()) return;

        this.fetchPhoneNumbers();
    }

    /** Phone number lookup requires an already-saved channel (the TwilioChannel row must exist server-side). */
    phoneNumberSelectDisabled(): boolean {
        const sid = this.form?.get('account_sid')?.value;
        const secretId = this.form?.get('auth_token_secret_id')?.value;
        return !sid || !secretId;
    }

    private resetPhoneNumbers(): void {
        this.phoneNumbers.set([]);
        this.phonesFetched.set(false);
        this.phoneLoadError.set(null);
        this.form.get('phone_number')?.setValue(null, { emitEvent: false });
    }

    private fetchPhoneNumbers(): void {
        const accountSid = this.form.value.account_sid;
        const authTokenSecretId = this.form.value.auth_token_secret_id;

        if (!accountSid || !authTokenSecretId) {
            this.phoneLoadError.set('Missing Twilio credentials.');
            return;
        }

        const cached = this.getCachedPhones(accountSid, authTokenSecretId);
        if (cached) {
            this.phoneNumbers.set(cached);
            this.phonesFetched.set(true);
            return;
        }

        this.phoneNumbersLoading.set(true);
        this.phoneLoadError.set(null);

        this.channelService
            .getPhoneNumbersForChannel(accountSid, authTokenSecretId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (phones) => {
                    this.phoneNumbers.set(phones);
                    this.phonesFetched.set(true);
                    this.setCachedPhones(accountSid, authTokenSecretId, phones);
                    this.phoneNumbersLoading.set(false);
                },
                error: (err: HttpErrorResponse) => {
                    this.phonesFetched.set(true);
                    this.phoneLoadError.set(extractHttpErrorMessage(err));
                    this.phoneNumbersLoading.set(false);
                },
            });
    }

    private getCachedPhones(accountSid: string, authTokenSecretId: number | null): TwilioPhoneNumber[] | null {
        try {
            const raw = localStorage.getItem(this.PHONE_CACHE_KEY);
            if (!raw) return null;
            const cache = JSON.parse(raw) as {
                account_sid: string;
                auth_token_secret_id: number | null;
                phones: TwilioPhoneNumber[];
            };
            if (cache.account_sid === accountSid && cache.auth_token_secret_id === authTokenSecretId) {
                return cache.phones;
            }
            localStorage.removeItem(this.PHONE_CACHE_KEY);
            return null;
        } catch {
            return null;
        }
    }

    private setCachedPhones(accountSid: string, authTokenSecretId: number | null, phones: TwilioPhoneNumber[]): void {
        try {
            localStorage.setItem(
                this.PHONE_CACHE_KEY,
                JSON.stringify({ account_sid: accountSid, auth_token_secret_id: authTokenSecretId, phones })
            );
        } catch {
            // ignore storage quota errors
        }
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
