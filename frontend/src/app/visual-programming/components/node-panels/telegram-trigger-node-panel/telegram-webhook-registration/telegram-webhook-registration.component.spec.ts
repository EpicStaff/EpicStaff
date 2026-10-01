import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { FlowsApiService } from '../../../../../features/flows/services/flows-api.service';
import {
    TelegramRegistrationBlocker,
    TelegramRegistrationBlockerCode,
    TelegramWebhookInfo,
} from '../../../../core/models/telegram-trigger.model';
import { SidePanelService } from '../../../../services/side-panel.service';
import { TelegramWebhookRegistrationComponent } from './telegram-webhook-registration.component';

const REGISTERED_URL = 'https://other-tunnel.ngrok.app/webhooks/other-path/';
const EXPECTED_URL = 'https://this-tunnel.ngrok.app/webhooks/this-path/';
const NODE_ID = 'telegram-1';
const WARNING = '.telegram-registration__mismatch';
const BLOCKER = '.telegram-registration__blocker';
const REGISTER_BUTTON = '.telegram-registration__register button';
const REGISTER_ERROR = '.telegram-registration__register-error';
const VISUALLY_HIDDEN = '.telegram-registration__visually-hidden';
const REGISTERED_LABEL = '.telegram-registration__registered-label';
const MATCH_SUMMARY = 'Telegram is delivering to this trigger.';
const GENERIC_REGISTER_ERROR = "Couldn't register the webhook. Press Check to see the current status, then try again.";
const BOT_KEY_REJECTED_TEXT = 'Telegram rejected this bot key. Check the secret selected as the bot key on this node.';
const BOT_KEY_REJECTED_BODY = { status_code: 422, code: 'telegram_bot_key_rejected', message: 'raw server text' };
const TAKEOVER_HINT =
    'Telegram keeps only one webhook per bot key. Press Register to point it at this trigger instead (the other URL will stop receiving messages).';

function webhookInfo(overrides: Partial<TelegramWebhookInfo> = {}): TelegramWebhookInfo {
    return {
        registered_url: EXPECTED_URL,
        expected_url: EXPECTED_URL,
        is_match: true,
        pending_update_count: 0,
        last_error_message: null,
        last_error_date: null,
        registration_blocker: null,
        ...overrides,
    };
}

const NOT_REGISTERED = webhookInfo({ registered_url: null, is_match: false });
const MISMATCH = webhookInfo({ registered_url: REGISTERED_URL, is_match: false });

function blocker(
    code: TelegramRegistrationBlockerCode | string,
    message = 'Server says no.'
): TelegramRegistrationBlocker {
    return { code, message };
}

function httpError(status: HttpStatusCode, error: unknown = null): () => Observable<never> {
    return () => throwError(() => new HttpErrorResponse({ status, error }));
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
    registerTelegramTriggerWebhook: ReturnType<typeof vi.fn>;
    /** Visible status text, without the screen-reader summary or screen-reader-only labels. */
    text: () => string;
    announcement: () => string;
    clickRegister: () => void;
}

function setup(
    inputs: {
        backendId: number | null;
        botKeySecretId: number | null;
        hasUnsavedConnectionChanges?: boolean;
        readonly?: boolean;
    },
    response: () => Observable<TelegramWebhookInfo> = () => of(webhookInfo()),
    registerResponse: () => Observable<TelegramWebhookInfo> = () => of(webhookInfo())
): Setup {
    const getTelegramTriggerWebhookInfo = vi.fn(response);
    const registerTelegramTriggerWebhook = vi.fn(registerResponse);
    TestBed.configureTestingModule({
        providers: [
            { provide: FlowsApiService, useValue: { getTelegramTriggerWebhookInfo, registerTelegramTriggerWebhook } },
        ],
    });
    const fixture = TestBed.createComponent(TelegramWebhookRegistrationComponent);
    fixture.componentRef.setInput('nodeId', NODE_ID);
    fixture.componentRef.setInput('backendId', inputs.backendId);
    fixture.componentRef.setInput('botKeySecretId', inputs.botKeySecretId);
    fixture.componentRef.setInput('hasUnsavedConnectionChanges', inputs.hasUnsavedConnectionChanges ?? false);
    fixture.componentRef.setInput('readonly', inputs.readonly ?? false);
    fixture.detectChanges();
    const normalized = (selector: string) => (): string =>
        query(fixture, selector)?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    /** What is on screen: screen-reader-only labels are left out. */
    const visibleText = (): string => {
        const status = query(fixture, '.telegram-registration__status')?.cloneNode(true) as HTMLElement | undefined;
        status?.querySelectorAll(VISUALLY_HIDDEN).forEach((hidden) => hidden.remove());
        return status?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    };
    const clickRegister = (): void => {
        query(fixture, REGISTER_BUTTON)?.click();
        fixture.detectChanges();
    };
    return {
        fixture,
        getTelegramTriggerWebhookInfo,
        registerTelegramTriggerWebhook,
        text: visibleText,
        announcement: normalized('.telegram-registration__announcement'),
        clickRegister,
    };
}

function query(fixture: ComponentFixture<unknown>, selector: string): HTMLElement | null {
    return (fixture.nativeElement as HTMLElement).querySelector(selector);
}

/** The match state on screen: this trigger's URL is registered and nothing warns about it. */
function expectMatchShown(fixture: ComponentFixture<unknown>): void {
    expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(EXPECTED_URL);
    expect(query(fixture, WARNING)).toBeNull();
    expect(query(fixture, '.telegram-registration__not-registered')).toBeNull();
}

function registerButton(fixture: ComponentFixture<unknown>): HTMLButtonElement | null {
    return query(fixture, REGISTER_BUTTON) as HTMLButtonElement | null;
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

    it('warns with both URLs and offers Register when Telegram delivers to a different URL', () => {
        const { fixture, getTelegramTriggerWebhookInfo, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(MISMATCH)
        );

        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);
        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledWith(12);
        const warning = query(fixture, WARNING)?.textContent?.replace(/\s+/g, ' ');
        expect(warning).toContain('This bot key is registered to a different URL.');
        expect(warning).toContain(TAKEOVER_HINT);
        expect(registerButton(fixture)?.disabled).toBe(false);
        expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
        expect(query(fixture, '.telegram-registration__expected-url')?.textContent?.trim()).toBe(EXPECTED_URL);
        // Two URLs are on screen, so both keep visible labels.
        expect(query(fixture, REGISTERED_LABEL)?.matches(VISUALLY_HIDDEN)).toBe(false);
        expect(text()).toContain('Registered in Telegram:');
        expect(text()).toContain("This trigger's URL:");
        fixture.destroy();
    });

    // The panel's "Tunnel connected" status already says it works, so the match is not repeated on screen.
    it('shows only the registered URL, labelled for screen readers, when the URLs match', () => {
        const { fixture, text, announcement } = setup({ backendId: 12, botKeySecretId: 5 });

        expect(query(fixture, WARNING)).toBeNull();
        expect(registerButton(fixture)).toBeNull();
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        expect(text()).not.toContain('Registered in Telegram:');
        expect(text()).toBe(EXPECTED_URL);
        expect(announcement()).toBe(MATCH_SUMMARY);
        const label = query(fixture, REGISTERED_LABEL);
        expect(label?.textContent?.trim()).toBe('Registered in Telegram:');
        expect(label?.matches(VISUALLY_HIDDEN)).toBe(true);
        // The hidden label sits in the URL's row, right before it, so it is read as the URL's name.
        expect(label?.nextElementSibling?.textContent?.trim()).toBe(EXPECTED_URL);
        fixture.destroy();
    });

    it('says nothing is registered and offers Register when Telegram has no URL for the bot key', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () => of(NOT_REGISTERED));

        // The backend reports is_match false for "nothing registered" too; that is not a mismatch.
        expect(text()).toContain('No webhook registered for this bot key');
        expect(registerButton(fixture)?.disabled).toBe(false);
        expect(query(fixture, WARNING)).toBeNull();
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        fixture.destroy();
    });

    // Saving sends only changed nodes, so saving an unchanged node does not register anything.
    it.each([
        ['nothing is registered', NOT_REGISTERED],
        ['a different URL is registered', MISMATCH],
        ['the URLs match', webhookInfo()],
    ])('never promises that saving the flow registers the webhook when %s', (_label, info) => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () => of(info));

        expect(text()).not.toMatch(/save the flow|saving the flow/i);
        fixture.destroy();
    });

    it('shows the registered URL without a verdict when this trigger URL is unknown', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
            of(webhookInfo({ registered_url: REGISTERED_URL, expected_url: null, is_match: null }))
        );

        expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
        expect(query(fixture, WARNING)).toBeNull();
        expect(registerButton(fixture)).toBeNull();
        expect(text()).not.toContain('Telegram is delivering to this trigger');
        expect(text()).toContain("This trigger's URL is unavailable, so it can't be compared with the registered one.");
        // Only one URL is on screen, so its label is for screen readers only.
        expect(query(fixture, REGISTERED_LABEL)?.matches(VISUALLY_HIDDEN)).toBe(true);
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
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, httpError(HttpStatusCode.BadGateway));

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
        firstResponse.next(MISMATCH);
        fixture.detectChanges();

        expect(query(fixture, WARNING)).toBeNull();
        expectMatchShown(fixture);
        fixture.destroy();
    });

    it('treats a 400 with the telegram_bot_key_not_configured code as a missing bot key', () => {
        const { fixture, text } = setup(
            { backendId: 12, botKeySecretId: 5 },
            httpError(HttpStatusCode.BadRequest, {
                status_code: 400,
                code: 'telegram_bot_key_not_configured',
                message: 'This Telegram trigger node has no bot key configured.',
            })
        );

        expect(text()).toContain('Select a bot key and save the flow');
        expect(text()).not.toContain("Couldn't reach Telegram");
        fixture.destroy();
    });

    it.each([
        ['a 400 with another code', HttpStatusCode.BadRequest, { status_code: 400, code: 'invalid', message: 'x' }],
        ['a 403', HttpStatusCode.Forbidden, null],
        ['a 404', HttpStatusCode.NotFound, null],
        ['a 422 with another code', HttpStatusCode.UnprocessableEntity, { status_code: 422, code: 'x', message: 'x' }],
        ['a 500', HttpStatusCode.InternalServerError, null],
    ])('shows the generic error for %s, not a Telegram or bot key message', (_label, status, error) => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, httpError(status, error));

        expect(text()).toContain("Couldn't check the registration.");
        expect(text()).not.toContain("Couldn't reach Telegram");
        expect(text()).not.toContain('Select a bot key');
        expect(text()).not.toContain('Telegram rejected this bot key');
        fixture.destroy();
    });

    it('shows the fixed bot-key line, keeps Check and offers no Register when Telegram rejects the bot key', () => {
        const { fixture, text, announcement } = setup(
            { backendId: 12, botKeySecretId: 5 },
            httpError(HttpStatusCode.UnprocessableEntity, BOT_KEY_REJECTED_BODY)
        );

        expect(query(fixture, '.telegram-registration__bot-key-rejected')?.textContent?.trim()).toBe(
            BOT_KEY_REJECTED_TEXT
        );
        expect(text()).not.toContain('raw server text');
        expect(text()).not.toContain("Couldn't check the registration.");
        expect(registerButton(fixture)).toBeNull();
        const checkButton = query(fixture, 'app-button button') as HTMLButtonElement | null;
        expect(checkButton?.disabled).toBe(false);
        expect(announcement()).toBe('Telegram rejected the bot key.');
        fixture.destroy();
    });

    it('checks again from the bot-key-rejected state when Check is pressed', () => {
        const responses: Observable<TelegramWebhookInfo>[] = [
            httpError(HttpStatusCode.UnprocessableEntity, BOT_KEY_REJECTED_BODY)(),
            of(NOT_REGISTERED),
        ];
        const { fixture, getTelegramTriggerWebhookInfo, text } = setup(
            { backendId: 12, botKeySecretId: 5 },
            () => responses.shift()!
        );

        query(fixture, 'app-button button')?.click();
        fixture.detectChanges();

        expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(2);
        expect(text()).toContain('No webhook registered for this bot key');
        expect(registerButton(fixture)).not.toBeNull();
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

    it('notes that the status reflects the last saved configuration when the form has unsaved changes', () => {
        const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5, hasUnsavedConnectionChanges: true });

        expect(text()).toContain('This status reflects the last saved configuration');
        fixture.destroy();
    });

    describe('live region', () => {
        it('is a single short summary outside the header, the details and the buttons', () => {
            const { fixture, announcement } = setup({ backendId: 12, botKeySecretId: 5 }, () => of(MISMATCH));

            const liveRegions = (fixture.nativeElement as HTMLElement).querySelectorAll('[aria-live]');
            expect(liveRegions).toHaveLength(1);
            expect(liveRegions[0].getAttribute('aria-live')).toBe('polite');
            expect(liveRegions[0].classList).toContain('telegram-registration__announcement');
            expect(liveRegions[0].querySelector('app-button')).toBeNull();
            expect(announcement()).toBe('This bot key is registered to a different URL.');
            expect(query(fixture, '[role="alert"]')).toBeNull();
            fixture.destroy();
        });

        it.each<[string, () => Observable<TelegramWebhookInfo>, string]>([
            ['a match', () => of(webhookInfo()), 'Telegram is delivering to this trigger.'],
            ['nothing registered', () => of(NOT_REGISTERED), 'No webhook registered for this bot key.'],
            [
                'a blocker',
                () => of(webhookInfo({ registration_blocker: blocker('no_telegram_secret') })),
                'The webhook cannot be registered.',
            ],
            // An automatic first check has no verdict yet, so there is nothing to announce.
            ['a pending automatic check', () => new Subject<TelegramWebhookInfo>(), ''],
            ['a failed check', httpError(HttpStatusCode.InternalServerError), "Couldn't check the registration."],
        ])('summarises %s', (_label, response, summary) => {
            const { fixture, announcement } = setup({ backendId: 12, botKeySecretId: 5 }, response);

            expect(announcement()).toBe(summary);
            fixture.destroy();
        });

        it('keeps the previous verdict during an automatic refetch, so an unchanged verdict is not re-announced', () => {
            const refetch = new Subject<TelegramWebhookInfo>();
            const responses = [of(MISMATCH), refetch];
            const { fixture, text, announcement } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => responses.shift()!
            );

            TestBed.inject(SidePanelService).notifyGraphSaved();
            fixture.detectChanges();

            expect(text()).toContain('Checking Telegram');
            expect(announcement()).toBe('This bot key is registered to a different URL.');

            refetch.next(webhookInfo());
            fixture.detectChanges();
            expect(announcement()).toBe('Telegram is delivering to this trigger.');
            fixture.destroy();
        });

        it('announces the running check when the user presses Check', () => {
            const responses = [of(MISMATCH), new Subject<TelegramWebhookInfo>()];
            const { fixture, announcement } = setup({ backendId: 12, botKeySecretId: 5 }, () => responses.shift()!);

            query(fixture, 'app-button button')?.click();
            fixture.detectChanges();

            expect(announcement()).toBe('Checking Telegram…');
            fixture.destroy();
        });
    });

    describe('Register', () => {
        it('registers the saved node and shows the returned status', () => {
            const { fixture, registerTelegramTriggerWebhook, announcement, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(MISMATCH),
                () => of(webhookInfo())
            );

            clickRegister();

            expect(registerTelegramTriggerWebhook).toHaveBeenCalledExactlyOnceWith(12);
            expect(query(fixture, WARNING)).toBeNull();
            expect(registerButton(fixture)).toBeNull();
            expectMatchShown(fixture);
            expect(announcement()).toBe('Telegram is delivering to this trigger.');
            fixture.destroy();
        });

        it('keeps the status, disables Register and Check, and ignores clicks while registering', () => {
            const pending = new Subject<TelegramWebhookInfo>();
            const { fixture, registerTelegramTriggerWebhook, text, announcement, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(NOT_REGISTERED),
                () => pending
            );

            clickRegister();
            clickRegister();
            // A disabled button swallows clicks in a browser but not always in jsdom; the component
            // must drop a repeated request on its own.
            fixture.componentInstance['registerWebhook']();

            expect(registerTelegramTriggerWebhook).toHaveBeenCalledTimes(1);
            expect(registerButton(fixture)?.disabled).toBe(true);
            expect((query(fixture, 'app-button button') as HTMLButtonElement).disabled).toBe(true);
            expect(text()).toContain('No webhook registered for this bot key');
            expect(text()).toContain('Registering…');
            expect(announcement()).toBe('Registering the webhook…');
            fixture.destroy();
        });

        it('shows the blocker from a 409 and hides Register', () => {
            const { fixture, text, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(NOT_REGISTERED),
                httpError(HttpStatusCode.Conflict, {
                    status_code: 409,
                    code: 'telegram_registration_blocked',
                    message: 'Registration is blocked.',
                    registration_blocker: blocker('no_telegram_secret'),
                })
            );

            clickRegister();

            expect(query(fixture, BLOCKER)?.textContent).toContain('This webhook trigger has no Telegram secret');
            expect(registerButton(fixture)).toBeNull();
            expect(query(fixture, REGISTER_ERROR)).toBeNull();
            expect(text()).toContain('No webhook registered for this bot key');
            fixture.destroy();
        });

        it.each<[string, HttpStatusCode, unknown, string]>([
            [
                'a 502',
                HttpStatusCode.BadGateway,
                { status_code: 502, code: 'telegram_registration_failed', message: 'raw server text' },
                "Couldn't register the webhook: Telegram did not accept it. Press Check to see the current status, then try again.",
            ],
            [
                'a 503 tunnel error',
                HttpStatusCode.ServiceUnavailable,
                { status_code: 503, code: 'telegram_tunnel_unavailable', message: 'raw server text' },
                "Couldn't register the webhook: the trigger's tunnel is not available yet. Check the trigger's tunnel and try again.",
            ],
            [
                'a 502 with another code',
                HttpStatusCode.BadGateway,
                { status_code: 502, code: 'something_else', message: 'raw server text' },
                GENERIC_REGISTER_ERROR,
            ],
            [
                'a 403',
                HttpStatusCode.Forbidden,
                { status_code: 403, code: 'permission_denied', message: 'raw server text' },
                GENERIC_REGISTER_ERROR,
            ],
            [
                'a 500',
                HttpStatusCode.InternalServerError,
                { status_code: 500, code: 'secret_resolution_error', message: 'raw server text' },
                GENERIC_REGISTER_ERROR,
            ],
            [
                'a 422 with another code',
                HttpStatusCode.UnprocessableEntity,
                { status_code: 422, code: 'something_else', message: 'raw server text' },
                GENERIC_REGISTER_ERROR,
            ],
            [
                'a 409 without a blocker',
                HttpStatusCode.Conflict,
                { status_code: 409, code: 'telegram_registration_blocked', message: 'raw server text' },
                GENERIC_REGISTER_ERROR,
            ],
        ])('shows a muted error line for %s and keeps the status and Register', (_label, status, body, line) => {
            const { fixture, text, announcement, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(MISMATCH),
                httpError(status, body)
            );

            clickRegister();

            expect(query(fixture, REGISTER_ERROR)?.textContent?.replace(/\s+/g, ' ').trim()).toBe(line);
            expect(text()).not.toContain('raw server text');
            expect(query(fixture, WARNING)).not.toBeNull();
            expect(registerButton(fixture)?.disabled).toBe(false);
            expect(announcement()).toBe("Couldn't register the webhook.");
            fixture.destroy();
        });

        it('shows the fixed bot-key line, not the generic one, when Telegram rejects the bot key', () => {
            const { fixture, text, announcement, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(MISMATCH),
                httpError(HttpStatusCode.UnprocessableEntity, BOT_KEY_REJECTED_BODY)
            );

            clickRegister();

            expect(query(fixture, REGISTER_ERROR)?.textContent?.trim()).toBe(BOT_KEY_REJECTED_TEXT);
            expect(text()).not.toContain("Couldn't register the webhook");
            expect(text()).not.toContain('raw server text');
            // The previous status stays: Telegram was not changed.
            expect(query(fixture, WARNING)).not.toBeNull();
            expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
            expect(announcement()).toBe('Telegram rejected the bot key.');
            fixture.destroy();
        });

        it('says the webhook was registered but not read back for telegram_webhook_info_unavailable', () => {
            const { fixture, announcement, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(MISMATCH),
                httpError(HttpStatusCode.BadGateway, {
                    status_code: 502,
                    code: 'telegram_webhook_info_unavailable',
                    message: 'raw server text',
                })
            );

            clickRegister();

            expect(query(fixture, '.telegram-registration__register-unread')?.textContent?.trim()).toBe(
                'Registered, but the status could not be read back - press Check.'
            );
            expect(query(fixture, REGISTER_ERROR)).toBeNull();
            expect(announcement()).toBe('Registered, but the status could not be read back.');
            fixture.destroy();
        });

        it.each<
            [
                string,
                (
                    sidePanelService: SidePanelService,
                    fixture: ComponentFixture<TelegramWebhookRegistrationComponent>
                ) => void,
            ]
        >([
            ['a graph save', (sidePanelService) => sidePanelService.notifyGraphSaved()],
            [
                "this node's single-node save",
                (sidePanelService, fixture) => {
                    sidePanelService.markNodeSaving(NODE_ID);
                    fixture.detectChanges();
                    sidePanelService.clearNodeSaving();
                },
            ],
            ['a new saved bot key', (_sidePanelService, fixture) => fixture.componentRef.setInput('botKeySecretId', 6)],
            ['a Check press', (_sidePanelService, fixture) => fixture.componentInstance['refresh']()],
        ])('lets %s during Register finish the POST, shows its result, then fetches once', (_label, interrupt) => {
            const pendingRegister = new Subject<TelegramWebhookInfo>();
            const refetch = new Subject<TelegramWebhookInfo>();
            const responses = [of(NOT_REGISTERED), refetch];
            const { fixture, getTelegramTriggerWebhookInfo, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => responses.shift()!,
                () => pendingRegister
            );
            clickRegister();

            interrupt(TestBed.inject(SidePanelService), fixture);
            fixture.detectChanges();
            expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);
            expect(pendingRegister.observed).toBe(true);

            pendingRegister.next(webhookInfo());
            pendingRegister.complete();
            fixture.detectChanges();

            expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(2);
            refetch.next(webhookInfo());
            fixture.detectChanges();
            expectMatchShown(fixture);
            fixture.destroy();
        });

        it('shows the Register result without a refetch when nothing came in meanwhile', () => {
            const { fixture, getTelegramTriggerWebhookInfo, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(NOT_REGISTERED),
                () => of(webhookInfo())
            );

            clickRegister();

            expect(getTelegramTriggerWebhookInfo).toHaveBeenCalledTimes(1);
            expectMatchShown(fixture);
            fixture.destroy();
        });

        it('treats a 400 bot-key error as a missing bot key', () => {
            const { fixture, text, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(NOT_REGISTERED),
                httpError(HttpStatusCode.BadRequest, { status_code: 400, code: 'telegram_bot_key_not_configured' })
            );

            clickRegister();

            expect(text()).toContain('Select a bot key and save the flow');
            fixture.destroy();
        });

        it('clears a failed attempt once Check fetches the status again', () => {
            const { fixture, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5 },
                () => of(NOT_REGISTERED),
                httpError(HttpStatusCode.InternalServerError)
            );
            clickRegister();
            expect(query(fixture, REGISTER_ERROR)).not.toBeNull();

            query(fixture, 'app-button button')?.click();
            fixture.detectChanges();

            expect(query(fixture, REGISTER_ERROR)).toBeNull();
            fixture.destroy();
        });

        it('is hidden when the user cannot change the flow', () => {
            const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5, readonly: true }, () => of(MISMATCH));

            expect(registerButton(fixture)).toBeNull();
            expect(text()).not.toContain('Press Register');
            expect(query(fixture, 'app-button button')).not.toBeNull();
            fixture.destroy();
        });

        it('is disabled while the form has unsaved connection changes, and the note says why', () => {
            const { fixture, registerTelegramTriggerWebhook, text, clickRegister } = setup(
                { backendId: 12, botKeySecretId: 5, hasUnsavedConnectionChanges: true },
                () => of(NOT_REGISTERED)
            );

            clickRegister();

            expect(registerButton(fixture)?.disabled).toBe(true);
            expect(registerTelegramTriggerWebhook).not.toHaveBeenCalled();
            expect(text()).toContain('Register is unavailable until the changes are saved.');
            fixture.destroy();
        });
    });

    describe('registration blocker', () => {
        it.each<[TelegramRegistrationBlockerCode, string]>([
            [
                'no_webhook_trigger',
                'This node has no webhook trigger, so its webhook cannot be registered. Pick or create a webhook trigger above and save the flow.',
            ],
            [
                'no_tunnel_provider',
                'This webhook trigger has no tunnel provider, so Telegram has no public URL to deliver to. In Settings > Webhook Triggers, edit this trigger to use ngrok, then press Check.',
            ],
            [
                'localhost_provider',
                'This webhook trigger uses a localhost provider, which Telegram cannot reach. Pick or create an ngrok trigger above and save the flow.',
            ],
            [
                'auth_kind_conflict',
                'This webhook trigger already uses another kind of authentication, so it cannot be used for Telegram. Pick or create a different webhook trigger above and save the flow.',
            ],
            [
                'no_telegram_secret',
                'This webhook trigger has no Telegram secret, so its webhook cannot be registered. In Settings > Webhook Triggers, edit this trigger to add a Telegram secret, then press Check.',
            ],
            [
                'invalid_telegram_secret',
                "This webhook trigger's Telegram secret is not in a format Telegram accepts, so its webhook cannot be registered. In Settings > Webhook Triggers, edit this trigger to use a different Telegram secret, then press Check.",
            ],
            [
                'unresolvable_telegram_secret',
                "This webhook trigger's Telegram secret could not be read, so its webhook cannot be registered. In Settings > Webhook Triggers, edit this trigger to set its Telegram secret again, then press Check.",
            ],
        ])('shows its own copy for %s, not the server message', (code, copy) => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(webhookInfo({ registered_url: null, is_match: false, registration_blocker: blocker(code) }))
            );

            expect(query(fixture, BLOCKER)?.textContent?.trim()).toBe(copy);
            fixture.destroy();
        });

        it.each<TelegramRegistrationBlockerCode>([
            'no_webhook_trigger',
            'no_tunnel_provider',
            'localhost_provider',
            'auth_kind_conflict',
            'no_telegram_secret',
            'invalid_telegram_secret',
            'unresolvable_telegram_secret',
        ])('only describes %s, without a fix, to a user who cannot change the flow', (code) => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5, readonly: true }, () =>
                of(webhookInfo({ registered_url: null, is_match: false, registration_blocker: blocker(code) }))
            );

            const warning = query(fixture, BLOCKER)?.textContent?.trim() ?? '';
            expect(warning).not.toBe('');
            expect(warning).not.toMatch(/pick|create|settings|edit|press check|save/i);
            fixture.destroy();
        });

        it('shows the read-only copy for no_telegram_secret', () => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5, readonly: true }, () =>
                of(webhookInfo({ registration_blocker: blocker('no_telegram_secret') }))
            );

            expect(query(fixture, BLOCKER)?.textContent?.trim()).toBe(
                'This webhook trigger has no Telegram secret, so its webhook cannot be registered.'
            );
            fixture.destroy();
        });

        // The trigger select's own alert is not always rendered (no Webhooks:Read, list not loaded).
        it.each<TelegramRegistrationBlockerCode>(['localhost_provider', 'auth_kind_conflict'])(
            'shows %s even though the trigger select may flag it too',
            (code) => {
                const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                    of(webhookInfo({ registered_url: null, is_match: false, registration_blocker: blocker(code) }))
                );

                expect(query(fixture, BLOCKER)).not.toBeNull();
                expect(registerButton(fixture)).toBeNull();
                fixture.destroy();
            }
        );

        it('falls back to the server message for an unknown code', () => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(webhookInfo({ registration_blocker: blocker('brand_new_code', 'Something new blocks this.') }))
            );

            expect(query(fixture, BLOCKER)?.textContent?.trim()).toBe('Something new blocks this.');
            fixture.destroy();
        });

        it('hides Register when nothing is registered but registration is blocked', () => {
            const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(
                    webhookInfo({
                        registered_url: null,
                        is_match: false,
                        registration_blocker: blocker('no_telegram_secret'),
                    })
                )
            );

            expect(text()).toContain('No webhook registered for this bot key');
            expect(registerButton(fixture)).toBeNull();
            fixture.destroy();
        });

        it('keeps the mismatch warning and URLs but drops the Register sentence and button', () => {
            const { fixture, text } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(
                    webhookInfo({
                        registered_url: REGISTERED_URL,
                        is_match: false,
                        registration_blocker: blocker('no_tunnel_provider'),
                    })
                )
            );

            expect(query(fixture, WARNING)?.textContent).toContain('This bot key is registered to a different URL.');
            expect(query(fixture, '.telegram-registration__registered-url')?.textContent?.trim()).toBe(REGISTERED_URL);
            expect(query(fixture, '.telegram-registration__expected-url')?.textContent?.trim()).toBe(EXPECTED_URL);
            expect(query(fixture, BLOCKER)).not.toBeNull();
            expect(text()).not.toContain('Press Register');
            expect(registerButton(fixture)).toBeNull();
            fixture.destroy();
        });

        it('keeps the matching registered URL alongside the blocker', () => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(webhookInfo({ registration_blocker: blocker('invalid_telegram_secret') }))
            );

            expectMatchShown(fixture);
            expect(query(fixture, BLOCKER)).not.toBeNull();
            fixture.destroy();
        });

        it('shows no blocker warning when registration can run', () => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () => of(NOT_REGISTERED));

            expect(query(fixture, BLOCKER)).toBeNull();
            expect(registerButton(fixture)).not.toBeNull();
            fixture.destroy();
        });

        it('stays out of the live region and has no role="alert"', () => {
            const { fixture } = setup({ backendId: 12, botKeySecretId: 5 }, () =>
                of(webhookInfo({ registration_blocker: blocker('no_telegram_secret') }))
            );

            expect(query(fixture, `[aria-live] ${BLOCKER}`)).toBeNull();
            expect(query(fixture, '[role="alert"]')).toBeNull();
            fixture.destroy();
        });
    });
});
