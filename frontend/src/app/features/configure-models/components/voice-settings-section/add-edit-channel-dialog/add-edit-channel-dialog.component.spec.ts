import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, input, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { WebhookTriggerFieldComponent } from '@shared/components';
import { RealtimeChannel, TwilioChannel, WebhookTriggerModel } from '@shared/models';
import { RealtimeChannelService, SecretsApiService, WebhookTriggerService } from '@shared/services';
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

type TwilioSave = () => Observable<TwilioChannel>;

/**
 * Renders the dialog for a new channel. Creating the channel succeeds; the Twilio settings save answers through
 * `createTwilioChannel`. Updating a channel saved by an earlier attempt stays in flight.
 */
function render(createTwilioChannel: TwilioSave): ComponentFixture<AddEditChannelDialogComponent> {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: DialogRef,
                useValue: { keydownEvents: new Subject<KeyboardEvent>(), close: vi.fn() } as unknown as DialogRef,
            },
            { provide: DIALOG_DATA, useValue: { channel: null, action: 'create' } },
            {
                provide: RealtimeChannelService,
                useValue: {
                    createChannel: () => of(CREATED_CHANNEL),
                    updateChannel: () => NEVER,
                    createTwilioChannel,
                    channelsChanged$: new Subject<void>(),
                } as unknown as RealtimeChannelService,
            },
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            { provide: WebhookTriggerService, useValue: {} },
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
    fixture.componentInstance.form.patchValue({ name: 'Support line', account_sid: 'AC123', auth_token_secret_id: 5 });
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
