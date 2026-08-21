import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { GetNgrokConfigResponse, VoiceSettings } from '@shared/models';
import { NgrokConfigApiService } from '@shared/services';
import { switchMap } from 'rxjs/operators';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { AgentDefinition } from '../../../agent-definitions/models/agent-definition.model';
import { AgentDefinitionsApiService } from '../../../agent-definitions/services/agent-definitions-api.service';
import { TwilioPhoneNumber, VoiceSettingsService } from '../../services/voice-settings.service';

const PHONE_CACHE_TTL_MS = 60_000;

interface PhoneNumberCache {
    sid: string;
    token: string;
    numbers: TwilioPhoneNumber[];
    loadedAt: number;
}

@Component({
    selector: 'app-voice-settings-tab',
    templateUrl: './voice-settings-section.component.html',
    styleUrls: ['./voice-settings-section.component.scss'],
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        SelectComponent,
        HelpTooltipComponent,
        AppSvgIconComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoiceSettingsSectionComponent implements OnInit {
    private voiceSettingsService = inject(VoiceSettingsService);
    private ngrokApiService = inject(NgrokConfigApiService);
    private agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);
    private fb = inject(FormBuilder);

    private phoneCache: PhoneNumberCache | null = null;

    status = signal<LoadingState>(LoadingState.IDLE);
    configuringWebhook = signal(false);
    loadingPhoneNumbers = signal(false);
    testing = signal(false);
    voiceStreamUrl = signal<string | null>(null);

    private agents = signal<AgentDefinition[]>([]);
    private ngrokConfigs = signal<GetNgrokConfigResponse[]>([]);
    phoneNumbers = signal<TwilioPhoneNumber[]>([]);
    selectedPhoneSid = signal<string | null>(null);

    agentItems = computed<SelectItem[]>(() => this.agents().map((a) => ({ name: a.name, value: a.id })));

    ngrokItems = computed<SelectItem[]>(() =>
        this.ngrokConfigs().map((c) => ({
            name: c.webhook_full_url ? `${c.name} (${c.webhook_full_url})` : c.name,
            value: c.id,
        }))
    );

    phoneNumberItems = computed<SelectItem[]>(() =>
        this.phoneNumbers().map((p) => ({
            name: p.friendly_name ? `${p.friendly_name} (${p.phone_number})` : p.phone_number,
            tip: p.voice_url || 'No webhook configured',
            value: p.sid,
        }))
    );

    canConfigureWebhook = computed(() => !!this.selectedPhoneSid() && !!this.voiceStreamUrl());

    form = this.fb.group({
        twilio_account_sid: this.fb.nonNullable.control(''),
        twilio_auth_token: this.fb.nonNullable.control(''),
        voice_agent_definition: this.fb.control<number | null>(null),
        ngrok_config: this.fb.control<number | null>(null),
    });

    private formValue = toSignal(this.form.valueChanges, {
        initialValue: this.form.getRawValue(),
    });

    canTestCredentials = computed<boolean>(() => {
        const v = this.formValue();
        return !!v.twilio_account_sid && !!v.twilio_auth_token;
    });

    ngOnInit(): void {
        this.form
            .get('ngrok_config')!
            .valueChanges.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((id: number | null) => {
                const config = this.ngrokConfigs().find((c) => c.id === Number(id));
                this.voiceStreamUrl.set(this._streamUrlFromConfig(config?.webhook_full_url));
            });

        this.loadAll();
    }

    private loadAll(): void {
        this.status.set(LoadingState.LOADING);

        this.ngrokApiService
            .getNgrokConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => this.ngrokConfigs.set(configs),
                error: () => {},
            });

        // No server-side filter for "has a realtime config" — the flag comes inline on
        // AgentDefinitionRead, so narrow it here.
        this.agentDefinitionsApi
            .getAgentDefinitions()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (agents) =>
                    this.agents.set(agents.filter((a) => a.agent_definition_realtime_config_id != null)),
                error: () => {},
            });

        this.voiceSettingsService
            .get()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (vs: VoiceSettings) => {
                    this.form.patchValue(
                        {
                            twilio_account_sid: vs.twilio_account_sid,
                            twilio_auth_token: vs.twilio_auth_token,
                            voice_agent_definition: vs.voice_agent_definition,
                            ngrok_config: vs.ngrok_config,
                        },
                        { emitEvent: false }
                    );
                    const savedConfig = this.ngrokConfigs().find((c) => c.id === vs.ngrok_config);
                    this.voiceStreamUrl.set(this._streamUrlFromConfig(savedConfig?.webhook_full_url));
                    this.status.set(LoadingState.LOADED);

                    if (vs.twilio_account_sid && vs.twilio_auth_token) {
                        this.loadPhoneNumbers({ silent: true });
                    }
                },
                error: () => {
                    this.status.set(LoadingState.ERROR);
                },
            });
    }

    onPhoneSelectOpen(): void {
        this.loadPhoneNumbers();
    }

    private loadPhoneNumbers(opts?: { silent?: boolean }): void {
        const sid: string = this.form.get('twilio_account_sid')!.value ?? '';
        const token: string = this.form.get('twilio_auth_token')!.value ?? '';

        if (!sid || !token) {
            this.phoneNumbers.set([]);
            return;
        }

        const now = Date.now();
        const cacheValid =
            this.phoneCache !== null &&
            this.phoneCache.sid === sid &&
            this.phoneCache.token === token &&
            now - this.phoneCache.loadedAt < PHONE_CACHE_TTL_MS;

        if (cacheValid) {
            this.phoneNumbers.set(this.phoneCache!.numbers);
            return;
        }

        this.loadingPhoneNumbers.set(true);
        this.voiceSettingsService
            .getPhoneNumbers()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (numbers) => {
                    this.phoneCache = { sid, token, numbers, loadedAt: Date.now() };
                    this.phoneNumbers.set(numbers);
                    this.loadingPhoneNumbers.set(false);
                },
                error: () => {
                    this.loadingPhoneNumbers.set(false);
                    if (!opts?.silent) {
                        this.toastService.error('Failed to load Twilio phone numbers');
                    }
                },
            });
    }

    private _streamUrlFromConfig(webhookFullUrl?: string | null): string | null {
        if (!webhookFullUrl) return null;
        return webhookFullUrl.replace(/^https?:\/\//, 'wss://').replace(/\/$/, '') + '/voice/stream';
    }

    onPhoneNumberChange(sid: unknown): void {
        this.selectedPhoneSid.set(sid as string | null);
    }

    onTestCredentials(): void {
        if (this.testing() || !this.canTestCredentials()) return;
        this.testing.set(true);

        this.voiceSettingsService
            .update(this.form.value)
            .pipe(
                switchMap((vs: VoiceSettings) => {
                    const savedConfig = this.ngrokConfigs().find((c) => c.id === vs.ngrok_config);
                    this.voiceStreamUrl.set(this._streamUrlFromConfig(savedConfig?.webhook_full_url));
                    this.phoneCache = null;
                    return this.voiceSettingsService.getPhoneNumbers();
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (numbers) => {
                    const sid: string = this.form.get('twilio_account_sid')!.value ?? '';
                    const token: string = this.form.get('twilio_auth_token')!.value ?? '';
                    this.phoneCache = { sid, token, numbers, loadedAt: Date.now() };
                    this.phoneNumbers.set(numbers);
                    this.testing.set(false);
                    this.toastService.success('Twilio credentials verified');
                },
                error: () => {
                    this.testing.set(false);
                    this.toastService.error('Twilio credentials invalid');
                },
            });
    }

    onConfigureWebhook(): void {
        const sid = this.selectedPhoneSid();
        if (!sid || this.configuringWebhook()) return;
        this.configuringWebhook.set(true);
        this.voiceSettingsService
            .configureWebhook(sid)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (res) => {
                    this.phoneCache = null;
                    this.configuringWebhook.set(false);
                    this.toastService.success(`Webhook configured: ${res.webhook_url}`);
                },
                error: () => {
                    this.configuringWebhook.set(false);
                    this.toastService.error('Failed to configure webhook');
                },
            });
    }
}
