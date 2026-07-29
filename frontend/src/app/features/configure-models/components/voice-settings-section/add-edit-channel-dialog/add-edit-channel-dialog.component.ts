import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgIf } from '@angular/common';
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
import { WebhookTriggerService } from '@shared/services';
import { Observable, of, switchMap } from 'rxjs';

import { RealtimeChannel, TwilioChannel } from '../../../../../shared/models/realtime-voice/realtime-channel.model';
import { RealtimeChannelService, TwilioPhoneNumber } from '../../../../../shared/services/realtime-channel.service';
import {
    WebhookTriggerModel,
    WebhookTriggerWrite,
} from '../../../../../visual-programming/core/models/webhook-trigger.model';
import { GetAgentRequest } from '../../../../staff/models/agent.model';
import { AgentsService } from '../../../../staff/services/staff.service';

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
        NgIf,
        WebhookTriggerFieldComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddEditChannelDialogComponent implements OnInit {
    private fb = inject(FormBuilder);
    private dialogRef = inject(DialogRef);
    private channelService = inject(RealtimeChannelService);
    private agentsService = inject(AgentsService);
    private webhookTriggerService = inject(WebhookTriggerService);
    private destroyRef = inject(DestroyRef);

    data: AddEditChannelDialogData = inject(DIALOG_DATA);

    isSubmitting = signal(false);
    errorMessage = signal<string | null>(null);

    private savedChannel = signal<RealtimeChannel | null>(this.data.channel);
    /** The trigger model resolved by the field (picked existing, or inline draft). */
    private resolvedTrigger = signal<WebhookTriggerModel | null>(this.data.channel?.twilio?.webhook_trigger ?? null);
    liveUrl = signal<string | null>(this.data.channel?.twilio?.webhook_trigger?.live_url ?? null);

    private agents = signal<GetAgentRequest[]>([]);
    private phoneNumbers = signal<TwilioPhoneNumber[]>([]);
    private phonesFetched = signal<boolean>(false);
    phoneNumbersLoading = signal<boolean>(false);
    phoneLoadError = signal<string | null>(null);

    private readonly PHONE_CACHE_KEY = 'twilio_phone_numbers_cache';

    agentItems = computed<SelectItem[]>(() => [
        { name: '— None —', value: null },
        ...this.agents().map((a) => ({ name: a.role, value: a.id })),
    ]);

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
            realtime_agent: [ch?.realtime_agent ?? null],
            is_active: [ch?.is_active ?? true],
            account_sid: [tw?.account_sid ?? ''],
            auth_token: [tw?.auth_token ?? ''],
            phone_number: [tw?.phone_number ?? ''],
            webhook_trigger: [(tw?.webhook_trigger ?? null) as WebhookTriggerWrite | null],
        });

        this.agentsService
            .getAgentsWithRealtimeConfig()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ next: (agents) => this.agents.set(agents), error: () => {} });

        this.form
            .get('account_sid')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.resetPhoneNumbers());

        this.form
            .get('auth_token')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.resetPhoneNumbers());

        if (tw?.account_sid && tw?.auth_token && tw?.phone_number) {
            this.fetchPhoneNumbers(tw.account_sid, tw.auth_token);
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
        this.liveUrl.set(trigger?.live_url ?? null);
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
                    realtime_agent: v.realtime_agent ?? null,
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
                            v.auth_token,
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
                    realtime_agent: v.realtime_agent ?? null,
                    is_active: v.is_active,
                })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.savedChannel.set({
                            ...saved,
                            name: v.name,
                            realtime_agent: v.realtime_agent ?? null,
                            is_active: v.is_active,
                        });
                        this.channelService.channelsChanged$.next();
                        this.saveTwilioChannel(
                            saved.id,
                            saved.token,
                            v.account_sid,
                            v.auth_token,
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
        authToken: string,
        phoneNumber: string,
        existingTwilio: TwilioChannel | null
    ): void {
        const hasTwilioData = accountSid || authToken || phoneNumber;

        if (!hasTwilioData) {
            this.dialogRef.close(true);
            return;
        }

        // Resolve the webhook trigger first (write = int PK on TwilioChannel), then attach its id.
        this.resolveWebhookTrigger()
            .pipe(
                switchMap((trigger) => {
                    this.liveUrl.set(trigger?.live_url ?? null);
                    const webhookTriggerId = trigger?.id ?? null;
                    const obs = existingTwilio
                        ? this.channelService.updateTwilioChannel({
                              channel: existingTwilio.channel,
                              account_sid: accountSid,
                              auth_token: authToken,
                              phone_number: phoneNumber || null,
                              webhook_trigger: webhookTriggerId,
                          })
                        : this.channelService.createTwilioChannel({
                              channel: channelId,
                              account_sid: accountSid,
                              auth_token: authToken,
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
        return value.id
            ? this.webhookTriggerService.update(value.id, value)
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
        const accountSid = this.form.get('account_sid')?.value?.trim();
        const authToken = this.form.get('auth_token')?.value?.trim();
        if (!accountSid || !authToken) return;
        if (this.phoneNumbersLoading() || this.phonesFetched()) return;
        this.fetchPhoneNumbers(accountSid, authToken);
    }

    private resetPhoneNumbers(): void {
        this.phoneNumbers.set([]);
        this.phonesFetched.set(false);
        this.phoneLoadError.set(null);
        this.form.get('phone_number')?.setValue(null, { emitEvent: false });
    }

    private fetchPhoneNumbers(accountSid: string, authToken: string): void {
        const cached = this.getCachedPhones(accountSid, authToken);
        if (cached) {
            this.phoneNumbers.set(cached);
            this.phonesFetched.set(true);
            return;
        }

        this.phoneNumbersLoading.set(true);
        this.phoneLoadError.set(null);
        this.channelService
            .getPhoneNumbers(accountSid, authToken)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (phones) => {
                    this.phoneNumbers.set(phones);
                    this.phonesFetched.set(true);
                    this.setCachedPhones(accountSid, authToken, phones);
                    this.phoneNumbersLoading.set(false);
                },
                error: () => {
                    this.phonesFetched.set(true);
                    this.phoneLoadError.set('Failed to load phone numbers. Check your credentials.');
                    this.phoneNumbersLoading.set(false);
                },
            });
    }

    private getCachedPhones(accountSid: string, authToken: string): TwilioPhoneNumber[] | null {
        try {
            const raw = localStorage.getItem(this.PHONE_CACHE_KEY);
            if (!raw) return null;
            const cache = JSON.parse(raw) as { account_sid: string; auth_token: string; phones: TwilioPhoneNumber[] };
            if (cache.account_sid === accountSid && cache.auth_token === authToken) return cache.phones;
            localStorage.removeItem(this.PHONE_CACHE_KEY);
            return null;
        } catch {
            return null;
        }
    }

    private setCachedPhones(accountSid: string, authToken: string, phones: TwilioPhoneNumber[]): void {
        try {
            localStorage.setItem(
                this.PHONE_CACHE_KEY,
                JSON.stringify({ account_sid: accountSid, auth_token: authToken, phones })
            );
        } catch {
            // ignore storage quota errors
        }
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
