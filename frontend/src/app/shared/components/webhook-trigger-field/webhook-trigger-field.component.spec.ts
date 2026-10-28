import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { Secret, WebhookTriggerAuth, WebhookTriggerModel, WebhookTriggerWrite } from '@shared/models';
import { SecretsStorageService, WebhookTriggerService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { WebhookTriggerFieldComponent } from './webhook-trigger-field.component';

const BOT_SECRET = { id: 7, name: 'Bot secret', tail: 'eqwe' } as Secret;
const OTHER_SECRET = { id: 8, name: 'Other secret', tail: 'zzzz' } as Secret;
/** TELEGRAM_TRIGGER's ngrok token (id 5), in the recycle bin. */
const BINNED_TOKEN = { id: 5, name: 'Old tunnel token' };

const TELEGRAM_TRIGGER: WebhookTriggerModel = {
    id: 3,
    path: 'telegram-bot',
    provider_type: 'ngrok',
    ngrok_config: { name: 'bot-tunnel', auth_token_secret_id: 5, domain: null, region: 'eu' },
    localhost_config: null,
    auth: { kind: 'telegram', secret_tail: 'eqwe', secret_id: BOT_SECRET.id },
};

const NEW_TRIGGER: WebhookTriggerModel = { ...TELEGRAM_TRIGGER, id: undefined, auth: undefined };

@Component({
    template: `<app-webhook-trigger-field
        [formControl]="control"
        [allowPickExisting]="false"
        [showAuth]="showAuth"
        [readonly]="readonly"
    />`,
    imports: [ReactiveFormsModule, WebhookTriggerFieldComponent],
})
class HostComponent {
    readonly control = new FormControl<WebhookTriggerWrite | null>(null);
    showAuth = true;
    readonly = false;
}

interface RenderOptions {
    secrets?: Secret[];
    showAuth?: boolean;
    readonly?: boolean;
}

function withAuth(auth: WebhookTriggerAuth | null): WebhookTriggerModel {
    return { ...TELEGRAM_TRIGGER, auth };
}

function render(trigger: WebhookTriggerModel, options: RenderOptions = {}) {
    const secrets: WritableSignal<Secret[]> = signal(options.secrets ?? [BOT_SECRET, OTHER_SECRET]);
    TestBed.configureTestingModule({
        providers: [
            { provide: WebhookTriggerService, useValue: { list: () => of([]), changed$: new Subject<void>() } },
            {
                provide: SecretsStorageService,
                useValue: {
                    secrets,
                    getSecrets: () => of(secrets()),
                    maskTail: (tail: string) => `••••${tail}`,
                    // Like the real storage: live secrets, plus the selected binned one.
                    selectItems: (selected: number | null) => [
                        ...secrets().map((secret) => ({
                            name: secret.name,
                            value: secret.id,
                            tip: `••••${secret.tail}`,
                        })),
                        ...(selected === BINNED_TOKEN.id
                            ? [{ name: `${BINNED_TOKEN.name} (in the recycle bin)`, value: BINNED_TOKEN.id }]
                            : []),
                    ],
                    isBinned: (id: number) => id === BINNED_TOKEN.id,
                },
            },
        ],
    });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.componentInstance.showAuth = options.showAuth ?? true;
    fixture.componentInstance.readonly = options.readonly ?? false;
    fixture.componentInstance.control.setValue(trigger);
    fixture.detectChanges();
    const field = fixture.debugElement.query(By.directive(WebhookTriggerFieldComponent))
        .componentInstance as WebhookTriggerFieldComponent;
    return { fixture, field, control: fixture.componentInstance.control, secrets };
}

function selectButton(fixture: ComponentFixture<HostComponent>, controlName: string): HTMLButtonElement | null {
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
        `app-select[formcontrolname="${controlName}"] .selector__btn`
    );
}

function selectButtonText(fixture: ComponentFixture<HostComponent>, controlName: string): string | null {
    return selectButton(fixture, controlName)?.textContent?.trim() ?? null;
}

function text(fixture: ComponentFixture<HostComponent>, selector: string): string {
    fixture.detectChanges();
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll(selector))
        .map((element) => element.textContent?.replace(/\s+/g, ' ').trim() ?? '')
        .join(' | ');
}

/** The plain-text value a read-only input or select shows for a form control. */
function readonlyText(fixture: ComponentFixture<HostComponent>, controlName: string): string | null {
    fixture.detectChanges();
    const value = (fixture.nativeElement as HTMLElement).querySelector(
        `[formcontrolname="${controlName}"] .readonly-value, [formcontrolname="${controlName}"] .selector__readonly-value`
    );
    return value?.textContent?.trim() ?? null;
}

function emittedTrigger(control: FormControl<WebhookTriggerWrite | null>): WebhookTriggerModel {
    return control.value as WebhookTriggerModel;
}

/** jsdom has no ResizeObserver, which the overflow tooltips rendered here (as in app-select) need. */
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('WebhookTriggerFieldComponent', () => {
    it('names a binned tunnel token, with the note, though the trigger was loaded without events', () => {
        const { fixture } = render(TELEGRAM_TRIGGER);

        expect(selectButtonText(fixture, 'ngrok_auth_token_secret_id')).toBe('Old tunnel token (in the recycle bin)');
        expect(text(fixture, '.binned-secret-note')).toContain('This secret is in the recycle bin');
    });

    it('still names the tunnel token as the current secret when it is missing from the secrets list', () => {
        const { fixture } = render({
            ...TELEGRAM_TRIGGER,
            ngrok_config: { name: 'bot-tunnel', auth_token_secret_id: 42, domain: null, region: 'eu' },
        });

        expect(selectButtonText(fixture, 'ngrok_auth_token_secret_id')).toBe('Current secret');
    });

    it('never offers the binned tunnel token as an auth secret', () => {
        const { field } = render(TELEGRAM_TRIGGER);

        expect(field['authSecretItems']().map((item) => item.value)).not.toContain(BINNED_TOKEN.id);
    });

    describe('existing telegram trigger', () => {
        it('pre-selects both the auth kind and the current secret', () => {
            const { fixture, field, control } = render(TELEGRAM_TRIGGER);

            expect(field.form.controls.auth_kind.value).toBe('telegram');
            expect(field.form.controls.auth_secret_id.value).toBe(BOT_SECRET.id);
            expect(selectButtonText(fixture, 'auth_kind')).toBe('Telegram Node');
            expect(selectButtonText(fixture, 'auth_secret_id')).toBe('Bot secret');
            expect(text(fixture, '.wt-hint')).toContain(
                'Current secret: ****eqwe (its value is never shown). Choose a different secret only to replace it.'
            );
            expect(control.valid).toBe(true);
        });

        it('locks the auth strategy while keeping its value in the form', () => {
            const { fixture, field } = render(TELEGRAM_TRIGGER);

            expect(selectButton(fixture, 'auth_kind')?.disabled).toBe(true);
            expect(field.form.controls.auth_kind.enabled).toBe(true);
            expect(field.form.value.auth_kind).toBe('telegram');
            expect(text(fixture, '.wt-hint')).toContain('The auth strategy of an existing trigger cannot be changed.');
        });

        it('sends neither auth_kind nor auth_secret_id when the auth fields are left untouched', () => {
            const { field, control } = render(TELEGRAM_TRIGGER);

            field.form.controls.path.setValue('telegram-bot-renamed');

            const payload = emittedTrigger(control);
            expect(payload.path).toBe('telegram-bot-renamed');
            expect('auth_kind' in payload).toBe(false);
            expect('auth_secret_id' in payload).toBe(false);
        });

        it('never sends auth_kind, even if the control value is changed programmatically', () => {
            const { field, control } = render(TELEGRAM_TRIGGER);

            field.form.controls.auth_kind.setValue('webhook');

            expect('auth_kind' in emittedTrigger(control)).toBe(false);
        });

        it('does not re-send the pre-selected secret when it is chosen again', () => {
            const { field, control } = render(TELEGRAM_TRIGGER);

            field.form.controls.auth_secret_id.setValue(BOT_SECRET.id);

            expect('auth_secret_id' in emittedTrigger(control)).toBe(false);
        });

        it('sends only auth_secret_id when a different secret is chosen', () => {
            const { field, control } = render(TELEGRAM_TRIGGER);

            field.form.controls.auth_secret_id.setValue(OTHER_SECRET.id);

            const payload = emittedTrigger(control);
            expect(payload.auth_secret_id).toBe(OTHER_SECRET.id);
            expect('auth_kind' in payload).toBe(false);
        });

        it('still renders the current secret when it is missing from the secrets list', () => {
            const { fixture, field, control } = render(
                withAuth({ kind: 'telegram', secret_tail: 'eqwe', secret_id: 99 })
            );

            expect(field.form.controls.auth_secret_id.value).toBe(99);
            expect(selectButtonText(fixture, 'auth_secret_id')).toBe('Current secret (****eqwe)');
            expect(text(fixture, '.wt-hint')).toContain('Current secret: ****eqwe');

            field.form.controls.path.setValue('telegram-bot-renamed');
            expect('auth_secret_id' in emittedTrigger(control)).toBe(false);
        });

        it('switches to the real secret name once the secrets list arrives after writeValue', () => {
            const { fixture, field, secrets } = render(TELEGRAM_TRIGGER, { secrets: [] });

            expect(selectButtonText(fixture, 'auth_secret_id')).toBe('Current secret (****eqwe)');

            secrets.set([BOT_SECRET, OTHER_SECRET]);

            expect(selectButtonText(fixture, 'auth_secret_id')).toBe('Bot secret');
            expect(field.form.controls.auth_secret_id.value).toBe(BOT_SECRET.id);
        });

        it('leaves the secret empty when secret_id is null and keeps it on save', () => {
            const { fixture, field, control } = render(
                withAuth({ kind: 'telegram', secret_tail: 'eqwe', secret_id: null })
            );

            expect(field.form.controls.auth_kind.value).toBe('telegram');
            expect(field.form.controls.auth_secret_id.value).toBeNull();
            expect(selectButtonText(fixture, 'auth_secret_id')).toBe('Keep current secret (****eqwe)');
            expect(text(fixture, '.wt-hint')).toContain('Leave Auth Secret empty to keep it');

            field.form.controls.path.setValue('telegram-bot-renamed');
            const payload = emittedTrigger(control);
            expect('auth_kind' in payload).toBe(false);
            expect('auth_secret_id' in payload).toBe(false);
        });

        it('treats a missing secret_id (older backend) like null', () => {
            const legacyAuth = { kind: 'telegram', secret_tail: 'eqwe' } as WebhookTriggerAuth;
            const { field } = render(withAuth(legacyAuth));

            expect(field.form.controls.auth_kind.value).toBe('telegram');
            expect(field.form.controls.auth_secret_id.value).toBeNull();
        });

        it('blocks switching the provider to localhost instead of clearing the kind', () => {
            const { fixture, field, control } = render(TELEGRAM_TRIGGER);

            field.form.controls.provider_type.setValue('localhost');
            field.form.controls.localhost_name.setValue('local');

            expect(field.form.controls.auth_kind.value).toBe('telegram');
            expect(field.form.controls.auth_secret_id.value).toBe(BOT_SECRET.id);
            expect(control.errors).toEqual({ authKindIncompatibleWithProvider: true });
            expect(text(fixture, '.wt-error')).toBe('Telegram and Twilio triggers cannot use the Localhost provider.');
            expect(selectButtonText(fixture, 'auth_kind')).toBe('Telegram Node');

            field.form.controls.provider_type.setValue('ngrok');
            expect(control.valid).toBe(true);
            expect(text(fixture, '.wt-error')).toBe('');
        });
    });

    it('allows an existing webhook trigger on localhost', () => {
        const { field, control } = render({
            ...TELEGRAM_TRIGGER,
            provider_type: 'localhost',
            ngrok_config: null,
            localhost_config: { name: 'local' },
            auth: { kind: 'webhook', secret_tail: 'zzzz', secret_id: OTHER_SECRET.id },
        });

        expect(field.form.controls.auth_kind.value).toBe('webhook');
        expect(field.authKindItems().map((item) => item.value)).toEqual(['webhook']);
        expect(control.valid).toBe(true);
    });

    it('does not pre-select a secret or show the secret select for an existing twilio trigger', () => {
        const { fixture, field, control } = render(withAuth({ kind: 'twilio', secret_tail: 'tttt', secret_id: 4 }));

        expect(field.form.controls.auth_kind.value).toBe('twilio');
        expect(field.form.controls.auth_secret_id.value).toBeNull();
        expect(selectButtonText(fixture, 'auth_secret_id')).toBeNull();
        expect(control.valid).toBe(true);
    });

    describe('trigger without auth', () => {
        it('leaves the auth strategy empty, editable and required', () => {
            const { fixture, field, control } = render(withAuth(null));

            expect(field.form.controls.auth_kind.value).toBeNull();
            expect(selectButtonText(fixture, 'auth_kind')).toBe('Select option');
            expect(selectButton(fixture, 'auth_kind')?.disabled).toBe(false);
            expect(selectButtonText(fixture, 'auth_secret_id')).toBeNull();
            expect(control.errors).toEqual({ authKindRequired: true });
        });

        it('sends the chosen kind and secret for a new auth', () => {
            const { field, control } = render(NEW_TRIGGER);

            field.form.controls.auth_kind.setValue('telegram');
            field.form.controls.auth_secret_id.setValue(BOT_SECRET.id);

            const payload = emittedTrigger(control);
            expect(payload.auth_kind).toBe('telegram');
            expect(payload.auth_secret_id).toBe(BOT_SECRET.id);
        });

        it('clears a new telegram choice when the provider switches to localhost', () => {
            const { field, control } = render(NEW_TRIGGER);
            field.form.controls.auth_kind.setValue('telegram');

            field.form.controls.provider_type.setValue('localhost');
            field.form.controls.localhost_name.setValue('local');

            expect(field.form.controls.auth_kind.value).toBeNull();
            expect(field.authKindItems().map((item) => item.value)).toEqual(['webhook']);
            expect(control.errors).toEqual({ authKindRequired: true });
        });
    });

    describe('read-only', () => {
        it.each<[string, string]>([
            ['path', 'telegram-bot'],
            ['provider_type', 'Ngrok'],
            ['ngrok_name', 'bot-tunnel'],
            ['ngrok_auth_token_secret_id', 'Old tunnel token (in the recycle bin)'],
            ['ngrok_domain', '—'],
            ['ngrok_region', 'Europe (eu)'],
            ['auth_kind', 'Telegram Node'],
            ['auth_secret_id', 'Bot secret'],
        ])('shows %s as plain text', (controlName, value) => {
            const { fixture } = render(TELEGRAM_TRIGGER, { readonly: true });

            expect(readonlyText(fixture, controlName)).toBe(value);
            expect(selectButton(fixture, controlName)).toBeNull();
        });

        it('shows the localhost name as plain text', () => {
            const { fixture } = render(
                {
                    ...TELEGRAM_TRIGGER,
                    provider_type: 'localhost',
                    ngrok_config: null,
                    localhost_config: { name: 'local' },
                    auth: { kind: 'webhook', secret_tail: 'zzzz', secret_id: OTHER_SECRET.id },
                },
                { readonly: true }
            );

            expect(readonlyText(fixture, 'localhost_name')).toBe('local');
        });

        it('leaves no input to type into', () => {
            const { fixture } = render(TELEGRAM_TRIGGER, { readonly: true });

            expect((fixture.nativeElement as HTMLElement).querySelectorAll('input, button')).toHaveLength(0);
        });

        it('states the current secret without inviting a change', () => {
            const { fixture } = render(TELEGRAM_TRIGGER, { readonly: true });

            expect(text(fixture, '.wt-hint')).toBe('Current secret: ****eqwe (its value is never shown).');
            expect(text(fixture, '.binned-secret-note')).toBe(
                "This secret is in the recycle bin, so it can't be used."
            );
        });

        it('states that no secret is set without inviting one', () => {
            const { fixture } = render(withAuth({ kind: 'telegram', secret_tail: null, secret_id: null }), {
                readonly: true,
            });

            expect(text(fixture, '.wt-hint')).toBe('No secret is set for this trigger yet.');
        });

        it('still names both current secrets when the secrets list is unavailable', () => {
            const { fixture } = render(
                {
                    ...TELEGRAM_TRIGGER,
                    ngrok_config: { name: 'bot-tunnel', auth_token_secret_id: 42, domain: null, region: 'eu' },
                },
                { secrets: [], readonly: true }
            );

            expect(readonlyText(fixture, 'ngrok_auth_token_secret_id')).toBe('Current secret');
            expect(readonlyText(fixture, 'auth_secret_id')).toBe('Current secret (****eqwe)');
        });
    });

    describe('showAuth = false (Twilio channel dialog)', () => {
        it('renders no auth fields and sends no auth keys for an existing trigger', () => {
            const { fixture, field, control } = render(TELEGRAM_TRIGGER, { showAuth: false });

            expect(selectButton(fixture, 'auth_kind')).toBeNull();
            expect(text(fixture, '.wt-hint')).toBe('');

            field.form.controls.path.setValue('telegram-bot-renamed');
            const payload = emittedTrigger(control);
            expect('auth_kind' in payload).toBe(false);
            expect('auth_secret_id' in payload).toBe(false);
            expect(control.valid).toBe(true);
        });

        it('reports no auth errors when the provider switches to localhost', () => {
            const { fixture, field, control } = render(TELEGRAM_TRIGGER, { showAuth: false });

            field.form.controls.provider_type.setValue('localhost');
            field.form.controls.localhost_name.setValue('local');

            expect(control.valid).toBe(true);
            expect(text(fixture, '.wt-error')).toBe('');
        });

        it('does not require an auth kind for a trigger without auth', () => {
            const { control } = render(NEW_TRIGGER, { showAuth: false });

            expect(control.valid).toBe(true);
        });
    });
});
