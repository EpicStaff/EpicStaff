import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    forwardRef,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ControlValueAccessor,
    FormBuilder,
    NG_VALIDATORS,
    NG_VALUE_ACCESSOR,
    ReactiveFormsModule,
    ValidationErrors,
    Validator,
    Validators,
} from '@angular/forms';

import {
    WebhookProviderType,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
    WebhookTriggerModel,
    WebhookTriggerWrite,
} from '../../../visual-programming/core/models/webhook-trigger.model';
import { SecretsStorageService } from '../../services/secrets/secrets-storage.service';
import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { CustomInputComponent } from '../form-input/form-input.component';
import { SelectComponent, SelectItem } from '../select/select.component';

export const WEBHOOK_NAME_PATTERN = /^[A-Za-z0-9\-._~/]*$/;

export const WEBHOOK_PROVIDER_ITEMS: SelectItem[] = [
    { name: 'Ngrok', value: 'ngrok' },
    { name: 'Localhost', value: 'localhost' },
];

export const WEBHOOK_REGION_ITEMS: SelectItem[] = [
    { name: 'Europe (eu)', value: 'eu' },
    { name: 'United States (us)', value: 'us' },
    { name: 'Asia/Pacific (ap)', value: 'ap' },
];

export const WEBHOOK_AUTH_KIND_ITEMS: SelectItem[] = [
    { name: 'Webhook Node', value: 'webhook' },
    { name: 'Telegram Node', value: 'telegram' },
    { name: 'Twilio', value: 'twilio' },
];

type Mode = 'existing' | 'new';

@Component({
    selector: 'app-webhook-trigger-field',
    standalone: true,
    imports: [ReactiveFormsModule, CustomInputComponent, SelectComponent],
    templateUrl: './webhook-trigger-field.component.html',
    styleUrls: ['./webhook-trigger-field.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => WebhookTriggerFieldComponent), multi: true },
        { provide: NG_VALIDATORS, useExisting: forwardRef(() => WebhookTriggerFieldComponent), multi: true },
    ],
})
export class WebhookTriggerFieldComponent implements ControlValueAccessor, Validator, OnInit {
    private fb = inject(FormBuilder);
    private service = inject(WebhookTriggerService);
    private secretsStorageService = inject(SecretsStorageService);
    private destroyRef = inject(DestroyRef);

    /** Allow choosing an existing trigger (reference by id). Off for the management create/edit dialog. */
    allowPickExisting = input<boolean>(true);
    /** Require a trigger to be provided (gates the parent form). */
    pathRequired = input<boolean>(true);
    /** Allow the localhost provider. Off for Twilio (it can't reach localhost webhooks). */
    allowLocalhost = input<boolean>(true);
    showAuth = input<boolean>(true);
    activeColor = input<string>('#685fff');

    /** Emits the resolved trigger model (the picked existing one, or the inline draft). */
    triggerResolved = output<WebhookTriggerModel | null>();

    mode = signal<Mode>('new');
    providerType = signal<WebhookProviderType | null>(null);
    authKindValue = signal<WebhookTriggerAuthKind | null>(null);
    triggers = signal<WebhookTriggerModel[]>([]);
    private triggersLoaded = signal(false);
    selectedExistingId = signal<number | null>(null);
    private editingId: number | undefined;
    private disabled = signal(false);
    existingAuth = signal<WebhookTriggerAuth | null>(null);

    providerItems = computed<SelectItem[]>(() =>
        this.allowLocalhost() ? WEBHOOK_PROVIDER_ITEMS : WEBHOOK_PROVIDER_ITEMS.filter((i) => i.value !== 'localhost')
    );
    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );
    readonly regionItems = WEBHOOK_REGION_ITEMS;
    readonly authKindItems: SelectItem[] = WEBHOOK_AUTH_KIND_ITEMS;
    readonly modeItems: SelectItem[] = [
        { name: 'Create new', value: 'new' },
        { name: 'Use existing', value: 'existing' },
    ];

    form = this.fb.group({
        path: ['', [Validators.required]],
        provider_type: [null as WebhookProviderType | null],
        ngrok_name: [''],
        ngrok_auth_token_secret_id: [null as number | null],
        ngrok_domain: [''],
        ngrok_region: ['eu'],
        localhost_name: [''],
        auth_kind: [null as WebhookTriggerAuthKind | null],
        auth_secret_id: [null as number | null],
    });

    existingItems = computed<SelectItem[]>(() => {
        const allowLocalhost = this.allowLocalhost();
        const items = this.triggers()
            .filter((t) => allowLocalhost || t.provider_type !== 'localhost')
            .map((t) => ({
                name: `${this.triggerName(t)} (${t.provider_type ?? 'none'})`,
                value: t.id as number,
            }));
        const selected = this.selectedExistingId();
        // Keep a referenced-but-missing (e.g. deleted) trigger visible so we don't silently drop the binding.
        if (selected != null && !this.triggers().some((t) => t.id === selected)) {
            items.unshift({ name: `Unknown / deleted (#${selected})`, value: selected });
        }
        return items;
    });

    selectedExistingTrigger = computed<WebhookTriggerModel | null>(
        () => this.triggers().find((t) => t.id === this.selectedExistingId()) ?? null
    );

    private onChange: (v: WebhookTriggerWrite | null) => void = () => {};
    private onTouched: () => void = () => {};
    private onValidatorChange: () => void = () => {};

    ngOnInit(): void {
        this.applyProviderValidators((this.form.value.provider_type as WebhookProviderType | null) ?? null);
        this.form.controls.provider_type.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((pt) => this.applyProviderValidators((pt as WebhookProviderType | null) ?? null));
        this.form.controls.auth_kind.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.form.controls.auth_secret_id.setValue(null, { emitEvent: false });
        });
        this.form.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            this.providerType.set((this.form.value.provider_type as WebhookProviderType | null) ?? null);
            this.authKindValue.set((this.form.value.auth_kind as WebhookTriggerAuthKind | null) ?? null);
            if (this.mode() === 'new') this.emit();
        });
        this.service.changed$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            if (this.triggersLoaded()) this.loadTriggers();
        });
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });
    }

    private applyProviderValidators(pt: WebhookProviderType | null): void {
        const ngrokName = this.form.controls.ngrok_name;
        const ngrokToken = this.form.controls.ngrok_auth_token_secret_id;
        const localhostName = this.form.controls.localhost_name;

        if (pt === 'ngrok') {
            ngrokName.setValidators([Validators.required]);
            ngrokToken.setValidators([Validators.required]);
            localhostName.clearValidators();
        } else if (pt === 'localhost') {
            ngrokName.clearValidators();
            ngrokToken.clearValidators();
            localhostName.setValidators([Validators.required]);
        } else {
            ngrokName.clearValidators();
            ngrokToken.clearValidators();
            localhostName.clearValidators();
        }
        ngrokName.updateValueAndValidity({ emitEvent: false });
        ngrokToken.updateValueAndValidity({ emitEvent: false });
        localhostName.updateValueAndValidity({ emitEvent: false });
        this.onValidatorChange();
    }

    authKindLabel(kind: WebhookTriggerAuthKind): string {
        return this.authKindItems.find((i) => i.value === kind)?.name ?? kind;
    }

    private triggerName(t: WebhookTriggerModel): string {
        switch (t.provider_type) {
            case 'ngrok':
                return t.ngrok_config?.name ?? '';
            case 'localhost':
                return t.localhost_config?.name ?? '';
            default:
                return t.path ?? '';
        }
    }

    onExistingOpened(): void {
        if (!this.triggersLoaded()) this.loadTriggers();
    }

    onModeChanged(value: unknown): void {
        this.mode.set(value === 'existing' ? 'existing' : 'new');
        if (this.mode() === 'existing' && !this.triggersLoaded()) this.loadTriggers();
        this.onTouched();
        this.emit();
    }

    onExistingChanged(value: unknown): void {
        this.selectedExistingId.set(typeof value === 'number' ? value : null);
        this.onTouched();
        this.emit();
    }

    private loadTriggers(): void {
        this.service
            .list()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (ts) => {
                    this.triggers.set(ts);
                    this.triggersLoaded.set(true);
                    if (this.mode() === 'existing') this.triggerResolved.emit(this.selectedExistingTrigger());
                },
                error: () => {},
            });
    }

    private emit(): void {
        const value = this.currentValue();
        this.onChange(value);
        this.triggerResolved.emit(this.resolvedModel(value));
        this.onValidatorChange();
    }

    private currentValue(): WebhookTriggerWrite | null {
        if (this.mode() === 'existing') return this.selectedExistingId();
        return this.buildNew();
    }

    private buildNew(): WebhookTriggerModel | null {
        const v = this.form.getRawValue();
        const path = (v.path ?? '').trim();
        if (!path) return null;
        const provider = (v.provider_type as WebhookProviderType | null) ?? null;
        return {
            ...(this.editingId ? { id: this.editingId } : {}),
            path,
            provider_type: provider,
            ngrok_config:
                provider === 'ngrok'
                    ? {
                          name: v.ngrok_name ?? '',
                          auth_token_secret_id: v.ngrok_auth_token_secret_id ?? null,
                          domain: v.ngrok_domain || null,
                          region: (v.ngrok_region as 'us' | 'eu' | 'ap') || 'eu',
                      }
                    : null,
            localhost_config: provider === 'localhost' ? { name: v.localhost_name ?? '' } : null,
            ...this.buildAuthPayload(v.auth_kind as WebhookTriggerAuthKind | null, v.auth_secret_id ?? null),
        };
    }

    private buildAuthPayload(
        authKind: WebhookTriggerAuthKind | null,
        authSecretId: number | null
    ): Pick<WebhookTriggerModel, 'auth_kind' | 'auth_secret_id'> {
        if (!this.showAuth()) return {};
        const existing = this.existingAuth();

        // New trigger (nothing to preserve): include whatever the user picked.
        if (!existing) {
            if (authKind == null) return {};
            return {
                auth_kind: authKind,
                ...(authKind !== 'twilio' && authSecretId != null ? { auth_secret_id: authSecretId } : {}),
            };
        }

        // Existing trigger: only send a key if the user changed it this session.
        const payload: Pick<WebhookTriggerModel, 'auth_kind' | 'auth_secret_id'> = {};
        if (authKind != null && authKind !== existing.kind) {
            payload.auth_kind = authKind;
        }
        if (authKind !== 'twilio' && authSecretId != null) {
            payload.auth_secret_id = authSecretId;
        }
        return payload;
    }

    private resolvedModel(value: WebhookTriggerWrite | null): WebhookTriggerModel | null {
        if (typeof value === 'number') return this.triggers().find((t) => t.id === value) ?? null;
        return value ?? null;
    }

    // --- ControlValueAccessor ---
    writeValue(value: WebhookTriggerWrite | null): void {
        if (typeof value === 'number') {
            this.mode.set('existing');
            this.selectedExistingId.set(value);
            this.editingId = undefined;
            if (!this.triggersLoaded()) this.loadTriggers();
            return;
        }
        if (value && typeof value === 'object') {
            this.mode.set('new');
            this.editingId = value.id;
            this.existingAuth.set(value.auth ?? null);
            this.form.patchValue(
                {
                    path: value.path ?? '',
                    provider_type: value.provider_type ?? null,
                    ngrok_name: value.ngrok_config?.name ?? '',
                    ngrok_auth_token_secret_id: value.ngrok_config?.auth_token_secret_id ?? null,
                    ngrok_domain: value.ngrok_config?.domain ?? '',
                    ngrok_region: value.ngrok_config?.region ?? 'eu',
                    localhost_name: value.localhost_config?.name ?? '',
                    auth_kind: null,
                    auth_secret_id: null,
                },
                { emitEvent: false }
            );
            this.providerType.set(value.provider_type ?? null);
            this.authKindValue.set(null);
            this.applyProviderValidators(value.provider_type ?? null);
            return;
        }
        this.mode.set('new');
        this.editingId = undefined;
        this.existingAuth.set(null);
        this.form.reset({ provider_type: null, ngrok_region: 'eu' }, { emitEvent: false });
        this.providerType.set(null);
        this.authKindValue.set(null);
        this.applyProviderValidators(null);
    }

    registerOnChange(fn: (v: WebhookTriggerWrite | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.disabled.set(isDisabled);
        isDisabled ? this.form.disable({ emitEvent: false }) : this.form.enable({ emitEvent: false });
    }

    // --- Validator ---
    validate(): ValidationErrors | null {
        if (this.disabled()) return null;
        const value = this.currentValue();
        if (this.pathRequired() && value == null) return { required: true };
        if (this.mode() === 'new') {
            const path = (this.form.value.path ?? '').trim();
            if (path && !WEBHOOK_NAME_PATTERN.test(path)) return { pattern: true };
            const provider = (this.form.value.provider_type as WebhookProviderType | null) ?? null;
            if ((this.pathRequired() || path) && !provider) {
                return { providerRequired: true };
            }
            if (provider === 'ngrok') {
                if (!(this.form.value.ngrok_name ?? '').trim()) return { ngrokNameRequired: true };
                if (this.form.value.ngrok_auth_token_secret_id == null) return { ngrokAuthTokenRequired: true };
            }
            if (provider === 'localhost') {
                if (!(this.form.value.localhost_name ?? '').trim()) return { localhostNameRequired: true };
            }
        }
        return null;
    }

    registerOnValidatorChange(fn: () => void): void {
        this.onValidatorChange = fn;
    }
}
