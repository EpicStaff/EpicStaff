import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { FlowsApiService } from '../../../../../features/flows/services/flows-api.service';
import { TelegramWebhookInfo } from '../../../../core/models/telegram-trigger.model';
import { SidePanelService } from '../../../../services/side-panel.service';
import { TelegramWebhookRegistrationComponent } from './telegram-webhook-registration.component';

const REGISTERED_URL = 'https://other-tunnel.ngrok.app/webhooks/other-path/';
const EXPECTED_URL = 'https://this-tunnel.ngrok.app/webhooks/this-path/';
const NODE_ID = 'telegram-1';
const WARNING = '.telegram-registration__warning';

function webhookInfo(overrides: Partial<TelegramWebhookInfo> = {}): TelegramWebhookInfo {
    return {
        registered_url: EXPECTED_URL,
        expected_url: EXPECTED_URL,
        is_match: true,
        pending_update_count: 0,
        last_error_message: null,
        last_error_date: null,
        ...overrides,
    };
}

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

interface Setup {
    fixture: ComponentFixture<TelegramWebhookRegistrationComponent>;
    getTelegramTriggerWebhookInfo: ReturnType<typeof vi.fn>;
    text: () => string;
}

function setup(
    inputs: {
        backendId: number | null;
        botKeySecretId: number | null;
        hasUnsavedConnectionChanges?: boolean;
    },
    response: () => Observable<TelegramWebhookInfo> = () => of(webhookInfo())
): Setup {
    const getTelegramTriggerWebhookInfo = vi.fn(response);
    TestBed.configureTestingModule({
        providers: [{ provide: FlowsApiService, useValue: { getTelegramTriggerWebhookInfo } }],
    });
    const fixture = TestBed.createComponent(TelegramWebhookRegistrationComponent);
    fixture.componentRef.setInput('nodeId', NODE_ID);
    fixture.componentRef.setInput('backendId', inputs.backendId);
    fixture.componentRef.setInput('botKeySecretId', inputs.botKeySecretId);
    fixture.componentRef.setInput('hasUnsavedConnectionChanges', inputs.hasUnsavedConnectionChanges ?? false);
    fixture.detectChanges();
    const text = (): string => (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ') ?? '';
    return { fixture, getTelegramTriggerWebhookInfo, text };
}

function query(fixture: ComponentFixture<unknown>, selector: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(selector);
}

describe('TelegramWebhookRegistrationComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('never calls the API for an unsaved node, even after a graph save', () => {
        const { fixture, getTelegramTriggerWebhookInfo, text } = setup({ backendId: null, botKeySecretId: 5 });

        TestBed.inject(SidePanelService).notifyGraphSaved();
        fixture.detectChanges();

        expect(getTelegramTriggerWebhookInfo).not.toHaveBeenCalled();
        expect(text()).toContain('Save the flow to check which webhook Telegram has registered for this bot key.');
        expect(query(fixture, 'app-button')).toBeNull();
        fixture.destroy();
    });

    it('never calls the API when no bot key is saved', () => {
        const { fixture, getTelegramTriggerWebhookInfo } = setup({ backendId: 12, botKeySecretId: null });

        TestBed.inject(SidePanelService).notifyGraphSaved();
        fixture.detectChanges();

        expect(getTelegramTriggerWebhookInfo).not.toHaveBeenCalled();
        fixture.destroy();
    });

    it('warns with both URLs when Telegram delivers to a different URL', () => {
        const { fixture, getTelegramTriggerWebhookInfo, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(webhookInfo({ registered_url: REGISTERED_URL, is_match: false }))
        );

        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledWith(12);
        const warning = query(fixture, WARNING);
        expect(warning?.textContent).toContain('This bot key is registered to a different URL.');
        expect(warning?.textContent).not.toMatch(/save/i);
        expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
        expect(query(fixture, '.telegram-registration__expected-url')?.textContent?.trim()).toBe(EXPECTED_URL);
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        fixture.destroy();
    });

    it('shows the success text and no warning when the URLs match', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 });

        expect(query(fixture, WARNING)).toBeNull();
        expect(text()).toContain('Telegram is delivering to this trigger');
        expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(EXPECTED_URL);
        fixture.destroy();
    });

    it('says nothing is registered when Telegram has no URL for the bot key', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(webhookInfo({ registered_url: null, is_match: false }))
        );

        // The backend reports is_match false for "nothing registered" too; that is not a mismatch.
        expect(text()).toContain('No webhook registered for this bot key');
        expect(query(fixture, WARNING)).toBeNull();
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        fixture.destroy();
    });

    it('shows the registered URL without a verdict when this trigger URL is unknown', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(webhookInfo({ registered_url: REGISTERED_URL, expected_url: null, is_match: null }))
        );

        expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
        expect(query(fixture, WARNING)).toBeNull();
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        expect(text()).toContain("This trigger's URL is unavailable, so it can't be compared with the registered one.");
        fixture.destroy();
    });

    it('shows Telegram last delivery error', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(webhookInfo({ last_error_message: 'Wrong response from the webhook: 502', last_error_date: null }))
        );

        expect(text()).toContain('Last delivery error: Wrong response from the webhook: 502');
        fixture.destroy();
    });

    it('shows a muted error text when Telegram cannot be reached', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            throwError(() => new HttpErrorResponse({ status: HttpStatusCode.BadGateway }))
        );

        expect(text()).toContain("Couldn't reach Telegram to check the registered webhook.");
        expect(query(fixture, WARNING)).toBeNull();
        fixture.destroy();
    });

    it('refetches after a graph save and on the Check button', () => {
        const { fixture, getTelegramTriggerWebhookInfo } = setup({ backendId: 12, botKeySecretId: 5 });
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);

        TestBed.inject(SidePanelService).notifyGraphSaved();
        fixture.detectChanges();
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(2);

        query(fixture, 'app-button button')?.click();
        fixture.detectChanges();
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(3);
        fixture.destroy();
    });

    it('refetches when a single-node save finishes, which does not emit graphSaved$', () => {
        const { fixture, getTelegramTriggerWebhookInfo } = setup({ backendId: 12, botKeySecretId: 5 });
        const sidePanelService = TestBed.inject(SidePanelService);

        sidePanelService.markNodeSaving(NODE_ID);
        fixture.detectChanges();
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);

        sidePanelService.clearNodeSaving();
        fixture.detectChanges();
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(2);
        fixture.destroy();
    });

    it('fetches once a newly saved node receives its backendId', () => {
        const { fixture, getTelegramTriggerWebhookInfo } = setup({ backendId: null, botKeySecretId: 5 });

        fixture.componentRef.setInput('backendId', 12);
        fixture.detectChanges();

        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledExactlyOnceWith(12);
        fixture.destroy();
    });

    it('keeps only the latest response when checks overlap', () => {
        const firstResponse = new Subject<TelegramWebhookInfo>();
        const responses = [firstResponse, of(webhookInfo())];
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () => responses.shift()!);
        expect(text()).toContain('Checking Telegram');

        TestBed.inject(SidePanelService).notifyGraphSaved();
        firstResponse.next(webhookInfo({ registered_url: REGISTERED_URL, is_match: false }));
        fixture.detectChanges();

        expect(query(fixture, WARNING)).toBeNull();
        expect(text()).toContain('Telegram is delivering to this trigger');
        fixture.destroy();
    });

    it('treats a 400 with the telegram_bot_key_not_configured code as a missing bot key', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: HttpStatusCode.BadRequest,
                        error: {
                            status_code: 400,
                            code: 'telegram_bot_key_not_configured',
                            message: 'This Telegram trigger node has no bot key configured.',
                        },
                    })
            )
        );

        expect(text()).toContain('Select a bot key and save the flow');
        expect(text()).not.toContain("Couldn't reach Telegram");
        fixture.destroy();
    });

    it.each([
        ['a 400 with another code', HttpStatusCode.BadRequest, { status_code: 400, code: 'invalid', message: 'x' }],
        ['a 403', HttpStatusCode.Forbidden, null],
        ['a 404', HttpStatusCode.NotFound, null],
        ['a 500', HttpStatusCode.InternalServerError, null],
    ])('shows the generic error for %s, not a Telegram or bot key message', (_label, status, error) => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            throwError(() => new HttpErrorResponse({ status, error }))
        );

        expect(text()).toContain("Couldn't check the registration.");
        expect(text()).not.toContain("Couldn't reach Telegram");
        expect(text()).not.toContain('Select a bot key');
        fixture.destroy();
    });

    it('shows the loading text, not the unsaved-node text, before the first check resolves', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () => new Subject<TelegramWebhookInfo>());

        expect(text()).toContain('Checking Telegram');
        expect(text()).not.toContain('Save the flow');
        fixture.destroy();
    });

    it('does not refetch when a single-node save of another node finishes', () => {
        const { fixture, getTelegramTriggerWebhookInfo } = setup({ backendId: 12, botKeySecretId: 5 });
        const sidePanelService = TestBed.inject(SidePanelService);

        sidePanelService.markNodeSaving('another-node');
        fixture.detectChanges();
        sidePanelService.clearNodeSaving();
        fixture.detectChanges();

        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);
        fixture.destroy();
    });

    it('keeps the live region on the status only, not on the header and Check button', () => {
        const { fixture } = setup({ backendId: 12, botKeySecretId: 5 });

        const liveRegions = (fixture.nativeElement as HTMLElement).querySelectorAll('[aria-live]');
        expect(liveRegions).toHaveLength(1);
        expect(liveRegions[0].classList).toContain('telegram-registration__status');
        expect(liveRegions[0].querySelector('app-button')).toBeNull();
        expect(query(fixture, '[role="alert"]')).toBeNull();
        fixture.destroy();
    });

    it('notes that the status reflects the last saved configuration when the form has unsaved changes', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5, hasUnsavedConnectionChanges: true });

        expect(text()).toContain('This status reflects the last saved configuration.');
        fixture.destroy();
    });
});
