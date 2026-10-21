import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { WebhookTriggerModel } from '@shared/models';
import { Subject } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { WebhookTriggerDialogComponent, WebhookTriggerDialogData } from './webhook-trigger-dialog.component';

const TRIGGER_URL = '/api/webhook-triggers/4/';
const BANNER_TEXT = "You can't edit it because you don't have the Use permission on flows.";

const TRIGGER: WebhookTriggerModel = {
    id: 4,
    path: 'orders',
    provider_type: 'ngrok',
    ngrok_config: { name: 'orders-tunnel', auth_token_secret_id: 5, domain: null, region: 'eu' },
    localhost_config: null,
    auth: { kind: 'telegram', secret_tail: 'eqwe', secret_id: 7 },
};

// jsdom has no ResizeObserver; the overflow directive behind <app-button> only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

interface Setup {
    fixture: ComponentFixture<WebhookTriggerDialogComponent>;
    host: HTMLElement;
    httpMock: HttpTestingController;
    close: ReturnType<typeof vi.fn>;
    keydown: Subject<KeyboardEvent>;
}

/** Renders the dialog for a user without Secrets read: both secret lists answer 403. */
function render(data: WebhookTriggerDialogData): Setup {
    const close = vi.fn();
    const keydown = new Subject<KeyboardEvent>();
    TestBed.configureTestingModule({
        imports: [WebhookTriggerDialogComponent],
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            { provide: DialogRef, useValue: { close, keydownEvents: keydown } },
            { provide: DIALOG_DATA, useValue: data },
        ],
    });
    const httpMock = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(WebhookTriggerDialogComponent);
    fixture.detectChanges();
    for (const request of httpMock.match((req) => req.url.includes('/secrets/'))) {
        request.flush({ detail: 'forbidden' }, { status: 403, statusText: 'Forbidden' });
    }
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, httpMock, close, keydown };
}

function buttons(host: HTMLElement): string[] {
    return Array.from(host.querySelectorAll('.dialog__actions app-button'), (button) =>
        (button.textContent ?? '').trim()
    );
}

function clickButton(host: HTMLElement, label: string): void {
    const button = Array.from(host.querySelectorAll<HTMLElement>('.dialog__actions app-button')).find(
        (element) => (element.textContent ?? '').trim() === label
    );
    button!.querySelector('button')!.click();
}

function text(host: HTMLElement, selector: string): string {
    return (host.querySelector(selector)?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function pressEnter(keydown: Subject<KeyboardEvent>, host: HTMLElement): void {
    const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
    Object.defineProperty(event, 'target', { value: host });
    keydown.next(event);
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('WebhookTriggerDialogComponent', () => {
    afterEach(() => TestBed.inject(HttpTestingController).verify());

    describe('read-only', () => {
        it('explains why the trigger cannot be edited, under the same title as editing', () => {
            const { host } = render({ trigger: TRIGGER, readonly: true });

            expect(text(host, '.dialog__header')).toBe('Edit Webhook Trigger');
            expect(text(host, '.dialog__readonly-banner')).toBe(BANNER_TEXT);
            expect(
                Array.from(host.querySelectorAll('.dialog__readonly-banner strong'), (strong) => strong.textContent)
            ).toEqual(['edit', 'Use']);
        });

        it('shows the fields as plain text, with no inputs to change them', () => {
            const { host } = render({ trigger: TRIGGER, readonly: true });

            expect(host.querySelectorAll('.dialog__form input, .dialog__form .selector__btn')).toHaveLength(0);
        });

        it('offers only Cancel, which closes without a result', () => {
            const { host, close } = render({ trigger: TRIGGER, readonly: true });

            expect(buttons(host)).toEqual(['Cancel']);
            clickButton(host, 'Cancel');

            expect(close).toHaveBeenCalledExactlyOnceWith(null);
        });

        it('saves nothing when Enter is pressed', () => {
            const { host, httpMock, close, keydown } = render({ trigger: TRIGGER, readonly: true });

            pressEnter(keydown, host);

            httpMock.expectNone(TRIGGER_URL);
            expect(close).not.toHaveBeenCalled();
        });
    });

    describe('editing', () => {
        it('shows the fields as inputs and offers Save, without the read-only banner', () => {
            const { host } = render({ trigger: TRIGGER });

            expect(host.querySelector('.dialog__readonly-banner')).toBeNull();
            expect(
                host.querySelectorAll('.dialog__form .readonly-value, .dialog__form .selector__readonly-value')
            ).toHaveLength(0);
            expect(buttons(host)).toEqual(['Cancel', 'Save']);
        });

        it('saves the trigger when Enter is pressed', () => {
            const { host, httpMock, keydown } = render({ trigger: TRIGGER });

            pressEnter(keydown, host);

            expect(httpMock.expectOne(TRIGGER_URL).request.method).toBe('PATCH');
        });
    });
});
