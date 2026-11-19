import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, input, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { WebhookTriggerFieldComponent } from '@shared/components';
import { RealtimeChannel, TwilioChannel, WebhookTriggerModel } from '@shared/models';
import { RealtimeChannelService, SecretsApiService, TwilioPhoneNumber, WebhookTriggerService } from '@shared/services';
import { NEVER, Observable, of, Subject, throwError } from 'rxjs';

import { AgentDefinitionsApiService } from '../../../../agent-definitions/services/agent-definitions-api.service';
import { AddEditChannelDialogComponent } from './add-edit-channel-dialog.component';

const CREATED_CHANNEL: RealtimeChannel = {
    id: 3,
    name: 'Support line',
    channel_type: 'twilio',
    token: 'channel-token',
    realtime_agent: null,
    realtime_agent_definition: null,
    is_enabled: true,
    created_by: null,
    created_at: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** The 400 the backend sends when the Twilio settings would reference a secret the caller may not use. */
const SECRET_USE_REFUSAL = new HttpErrorResponse({
    status: 400,
    error: {
        status_code: 400,
        code: 'invalid',
        message:
            'auth_token_secret_id: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
            'The existing selection was left unchanged. Ask an organization admin to grant it.',
    },
});

const SERVER_ERROR = new HttpErrorResponse({
    status: 500,
    error: { status_code: 500, code: 'Exception', message: 'Unpredictable error' },
});

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

/** Stands in for the webhook trigger field, which loads triggers and secrets of its own; none play a part here. */
@Component({
    selector: 'app-webhook-trigger-field',
    template: '',
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => WebhookTriggerFieldStubComponent), multi: true },
    ],
})
class WebhookTriggerFieldStubComponent implements ControlValueAccessor {
    readonly pathRequired = input(true);
    readonly allowedProviders = input<string[]>([]);
    readonly showAuth = input(true);
    readonly existingAuthKindFilter = input<string | null>(null);
    readonly triggerResolved = output<WebhookTriggerModel | null>();

    writeValue(): void {}
    registerOnChange(): void {}
    registerOnTouched(): void {}
}

type TwilioRowSent = Omit<TwilioChannel, 'webhook_trigger'>;
type TwilioSave = (row: TwilioRowSent) => Observable<TwilioChannel>;
type PhoneNumberLookup = () => Observable<TwilioPhoneNumber[]>;

const SUPPORT_PHONE: TwilioPhoneNumber = {
    sid: 'PN1',
    phone_number: '+15550100',
    friendly_name: 'Support',
    voice_url: null,
};

const TUNNEL_TRIGGER = { id: 7 } as WebhookTriggerModel;

/** The server saves the Twilio row as sent, with the tunnel trigger attached. */
const saveAsSent: TwilioSave = (row) => of({ ...row, webhook_trigger: TUNNEL_TRIGGER });

/** A channel saved earlier with its Twilio number and tunnel, as the edit dialog opens it. */
const EDITED_CHANNEL: RealtimeChannel = {
    ...CREATED_CHANNEL,
    twilio: {
        channel: CREATED_CHANNEL.id,
        account_sid: 'AC123',
        auth_token_secret_id: 5,
        phone_number: '+15550100',
        webhook_trigger: TUNNEL_TRIGGER,
    },
};

interface DialogSetup {
    /** Opens the dialog to edit this channel; without it the dialog is for a new channel. */
    channel?: RealtimeChannel;
    getPhoneNumbersForChannel?: PhoneNumberLookup;
    configureWebhook?: () => Observable<unknown>;
}

/**
 * Renders the dialog. For a new channel, creating the channel succeeds, the Twilio settings save answers through
 * `createTwilioChannel`, and updating a channel saved by an earlier attempt stays in flight. For an edited channel,
 * both updates are saved as sent. The phone number lookup and the webhook setup answer through `setup`; trigger 7
 * resolves to `TUNNEL_TRIGGER`.
 */
function render(
    createTwilioChannel: TwilioSave,
    { channel, getPhoneNumbersForChannel = () => of([]), configureWebhook = () => of({}) }: DialogSetup = {}
): ComponentFixture<AddEditChannelDialogComponent> {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            {
                provide: DIALOG_DATA,
                useValue: channel ? { channel, action: 'update' } : { channel: null, action: 'create' },
            },
            {
                provide: RealtimeChannelService,
                useValue: {
                    createChannel: () => of(CREATED_CHANNEL),
                    updateChannel: () => (channel ? of({}) : NEVER),
                    createTwilioChannel,
                    updateTwilioChannel: saveAsSent,
                    getPhoneNumbersForChannel,
                    configureWebhook,
                    channelsChanged$: new Subject<void>(),
                } as unknown as RealtimeChannelService,
            },
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            { provide: WebhookTriggerService, useValue: { getById: () => of(TUNNEL_TRIGGER) } },
            {
                provide: SecretsApiService,
                useValue: { getSecrets: () => of([]), getBinnedSecrets: () => of([]) } as unknown as SecretsApiService,
            },
        ],
    });
    TestBed.overrideComponent(AddEditChannelDialogComponent, {
        remove: { imports: [WebhookTriggerFieldComponent] },
        add: { imports: [WebhookTriggerFieldStubComponent] },
    });
    const fixture = TestBed.createComponent(AddEditChannelDialogComponent);
    fixture.detectChanges();
    if (!channel) {
        fixture.componentInstance.form.patchValue({
            name: 'Support line',
            account_sid: 'AC123',
            auth_token_secret_id: 5,
        });
    }
    return fixture;
}

function submit(fixture: ComponentFixture<AddEditChannelDialogComponent>): void {
    fixture.componentInstance.onSubmit();
    fixture.detectChanges();
}

function bannerText(fixture: ComponentFixture<AddEditChannelDialogComponent>): string {
    const banner = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('app-error-banner');
    return banner && !banner.hidden ? (banner.textContent ?? '').trim() : '';
}

describe('AddEditChannelDialogComponent save errors', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('shows a refused Twilio settings save in the banner, with the field label in words', () => {
        const fixture = render(() => throwError(() => SECRET_USE_REFUSAL));

        submit(fixture);

        expect(bannerText(fixture)).toBe(
            'Auth token secret: Changing the secrets referenced here requires the "Use" permission on Secrets. ' +
                'The existing selection was left unchanged. Ask an organization admin to grant it.'
        );
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('clears the banner when the channel is saved again', () => {
        const fixture = render(() => throwError(() => SECRET_USE_REFUSAL));
        submit(fixture);
        expect(bannerText(fixture)).not.toBe('');

        submit(fixture);

        expect(bannerText(fixture)).toBe('');
    });

    it("keeps the step's own message for a server error", () => {
        const fixture = render(() => throwError(() => SERVER_ERROR));

        submit(fixture);

        expect(bannerText(fixture)).toBe('Channel saved but Twilio settings failed to save.');
    });
});

describe('AddEditChannelDialogComponent phone numbers', () => {
    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        localStorage.clear();
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    it('asks the server in every dialog and keeps the account and its numbers out of the browser storage', () => {
        const lookup = vi.fn<PhoneNumberLookup>(() => of([SUPPORT_PHONE]));

        render(() => NEVER, { getPhoneNumbersForChannel: lookup }).componentInstance.onPhoneSelectOpened();
        TestBed.resetTestingModule();
        const reopened = render(() => NEVER, { getPhoneNumbersForChannel: lookup }).componentInstance;
        reopened.onPhoneSelectOpened();

        expect(lookup).toHaveBeenCalledTimes(2);
        expect(reopened.phoneNumberItems().map((item) => item.value)).toEqual([null, '+15550100']);
        expect(localStorage.length).toBe(0);
    });

    it('asks the server once while the same dialog stays open', () => {
        const lookup = vi.fn<PhoneNumberLookup>(() => of([SUPPORT_PHONE]));
        const dialog = render(() => NEVER, { getPhoneNumbersForChannel: lookup }).componentInstance;

        dialog.onPhoneSelectOpened();
        dialog.onPhoneSelectOpened();

        expect(lookup).toHaveBeenCalledTimes(1);
    });
});

describe('AddEditChannelDialogComponent webhook setup on save', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    /** Saves a new channel with a phone number and a tunnel picked, before the dialog has loaded any numbers. */
    function saveBeforeNumbersLoaded(setup: DialogSetup): ComponentFixture<AddEditChannelDialogComponent> {
        const fixture = render(saveAsSent, setup);
        fixture.componentInstance.form.patchValue({ phone_number: '+15550100', webhook_trigger: TUNNEL_TRIGGER.id });
        submit(fixture);
        return fixture;
    }

    it('points the webhook at the channel when an edit is saved before the numbers loaded on open', () => {
        const loadOnOpen = new Subject<TwilioPhoneNumber[]>();
        const lookups = [loadOnOpen, of([SUPPORT_PHONE])];
        const configureWebhook = vi.fn(() => of({}));
        const fixture = render(saveAsSent, {
            channel: EDITED_CHANNEL,
            getPhoneNumbersForChannel: () => lookups.shift()!,
            configureWebhook,
        });

        submit(fixture);

        expect(configureWebhook).toHaveBeenCalledWith('PN1', 'channel-token');
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalledWith(true);
    });

    it('points the webhook at the channel when the edit is saved again after the numbers failed to load', () => {
        const lookups = [throwError(() => SERVER_ERROR), throwError(() => SERVER_ERROR), of([SUPPORT_PHONE])];
        const configureWebhook = vi.fn(() => of({}));
        const fixture = render(saveAsSent, {
            channel: EDITED_CHANNEL,
            getPhoneNumbersForChannel: () => lookups.shift()!,
            configureWebhook,
        });
        submit(fixture);
        expect(bannerText(fixture)).not.toBe('');

        submit(fixture);

        expect(configureWebhook).toHaveBeenCalledWith('PN1', 'channel-token');
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalledWith(true);
    });

    it('looks the number up and points its webhook at the channel', () => {
        const configureWebhook = vi.fn(() => of({}));

        saveBeforeNumbersLoaded({ getPhoneNumbersForChannel: () => of([SUPPORT_PHONE]), configureWebhook });

        expect(configureWebhook).toHaveBeenCalledWith('PN1', 'channel-token');
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalledWith(true);
    });

    it('keeps the dialog open and says so when the number is not on the Twilio account', () => {
        const configureWebhook = vi.fn(() => of({}));

        const fixture = saveBeforeNumbersLoaded({ getPhoneNumbersForChannel: () => of([]), configureWebhook });

        expect(bannerText(fixture)).toBe(
            'Channel saved but +15550100 is not a number on this Twilio account, so its webhook was not configured.'
        );
        expect(configureWebhook).not.toHaveBeenCalled();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });

    it('keeps the dialog open and says so when the numbers fail to load', () => {
        const fixture = saveBeforeNumbersLoaded({ getPhoneNumbersForChannel: () => throwError(() => SERVER_ERROR) });

        expect(bannerText(fixture)).toBe(
            'Channel saved but the Twilio phone numbers failed to load, so the webhook was not configured.'
        );
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
    });
});
