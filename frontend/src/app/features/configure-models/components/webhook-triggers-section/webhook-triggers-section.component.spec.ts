import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    AuthorshipDetailsDialogService,
    ConfirmationDialogService,
    WebhookTriggerDialogComponent,
} from '@shared/components';
import { ActionCode, ResourceCode, WebhookTriggerFlowsResponse, WebhookTriggerModel } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { of, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { RecycleBinSettingsService } from '../../../../services/recycle-bin';
import { WebhookTriggersSectionComponent } from './webhook-triggers-section.component';

const TRIGGER: WebhookTriggerModel = {
    id: 4,
    path: 'orders',
    provider_type: 'ngrok',
    ngrok_config: { name: 'Orders tunnel', auth_token_secret_id: null, domain: null, region: 'eu' },
    localhost_config: null,
    live_url: null,
    auth: null,
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    created_at: '2026-03-12T13:28:23Z',
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-03-13T09:00:00Z',
};

// The model marks the authorship fields optional (it doubles as a form value); one the API left out.
const TRIGGER_WITHOUT_AUTHORSHIP: WebhookTriggerModel = {
    id: 5,
    path: 'legacy',
    provider_type: null,
    ngrok_config: null,
    localhost_config: null,
};

function configure(canWrite: boolean, triggers: WebhookTriggerModel[], open?: ReturnType<typeof vi.fn>): void {
    TestBed.configureTestingModule({
        providers: [
            { provide: WebhookTriggerService, useValue: { list: () => of(triggers), changed$: new Subject<void>() } },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: ToastService, useValue: {} },
            { provide: PermissionsService, useValue: { can: () => canWrite } },
            ...(open ? [{ provide: AuthorshipDetailsDialogService, useValue: { open } }] : []),
        ],
    });
}

function render(
    canWrite: boolean,
    triggers: WebhookTriggerModel[] = [TRIGGER]
): {
    fixture: ComponentFixture<WebhookTriggersSectionComponent>;
    overlay: HTMLElement;
    open: ReturnType<typeof vi.fn>;
} {
    const open = vi.fn();
    configure(canWrite, triggers, open);
    const fixture = TestBed.createComponent(WebhookTriggersSectionComponent);
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, overlay, open };
}

function moreButtons(host: HTMLElement): HTMLButtonElement[] {
    return Array.from(host.querySelectorAll<HTMLButtonElement>('[aria-label="More actions"]'));
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | null {
    return overlay.querySelector<HTMLButtonElement>('[role="menuitem"]');
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressKey(target: HTMLElement, key: string, keyCode: number): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    target.dispatchEvent(event);
    return event;
}

// jsdom has no ResizeObserver; the overflow directive behind the header's <app-button> only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('WebhookTriggersSectionComponent "View Details"', () => {
    it('puts the ⋮ button before Edit and Delete', () => {
        const { fixture } = render(true);
        const actions = (fixture.nativeElement as HTMLElement).querySelectorAll('.trigger-card__action');

        expect(Array.from(actions, (action) => action.getAttribute('aria-label'))).toEqual([
            'More actions',
            'Edit',
            'Delete',
        ]);
    });

    it('offers "View Details" to a user who can only read webhook triggers', () => {
        const { fixture, overlay } = render(false);
        const host = fixture.nativeElement as HTMLElement;

        expect(host.querySelectorAll('.trigger-card__action')).toHaveLength(1);
        moreButtons(host)[0].click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)?.textContent?.trim()).toBe('View Details');
    });

    it('marks the ⋮ button active while its menu is open', () => {
        const { fixture } = render(true);
        const trigger = moreButtons(fixture.nativeElement)[0];

        trigger.click();
        fixture.detectChanges();

        expect(trigger.classList).toContain('trigger-card__action--active');
        expect(trigger.getAttribute('aria-expanded')).toBe('true');
    });

    it('opens "Webhook Trigger Details" with the trigger\'s authorship, closing back to its ⋮ button', () => {
        const { fixture, overlay, open } = render(true);
        const trigger = moreButtons(fixture.nativeElement)[0];

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledExactlyOnceWith(
            'Webhook Trigger Details',
            {
                created_by: TRIGGER.created_by,
                created_at: TRIGGER.created_at,
                last_edited_by: TRIGGER.last_edited_by,
                last_edited_at: TRIGGER.last_edited_at,
            },
            trigger
        );
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('trigger-card__action--active');
    });

    it('opens the details of the row whose ⋮ was chosen, with absent authorship as null', () => {
        const { fixture, overlay, open } = render(true, [TRIGGER, TRIGGER_WITHOUT_AUTHORSHIP]);
        const trigger = moreButtons(fixture.nativeElement)[1];

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledExactlyOnceWith(
            'Webhook Trigger Details',
            { created_by: null, created_at: null, last_edited_by: null, last_edited_at: null },
            trigger
        );
    });
});

describe('WebhookTriggersSectionComponent "Edit"', () => {
    const LIST_URL = '/api/webhook-triggers/';
    const FLOWS_URL = `/api/webhook-triggers/${TRIGGER.id}/flows/`;
    const NOT_IN_USE: WebhookTriggerFlowsResponse = { flow_count: 0, flows: [] };
    const IN_USE: WebhookTriggerFlowsResponse = { flow_count: 1, flows: [{ id: 9, name: 'Orders' }] };

    interface EditSetup {
        fixture: ComponentFixture<WebhookTriggersSectionComponent>;
        httpMock: HttpTestingController;
        /** Read by the fake `can()` on every call, so a test can grant Flows:Use between presses. */
        access: { canRunFlows: boolean };
        open: ReturnType<typeof vi.spyOn>;
    }

    function renderForEdit(canRunFlows: boolean, triggers: WebhookTriggerModel[] = [TRIGGER]): EditSetup {
        const access = { canRunFlows };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: ToastService, useValue: {} },
                { provide: RecycleBinSettingsService, useValue: { retentionDays: signal(7) } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Flows && action === ActionCode.Use ? access.canRunFlows : true,
                    },
                },
            ],
        });
        const httpMock = TestBed.inject(HttpTestingController);
        const open = vi
            .spyOn(TestBed.inject(Dialog), 'open')
            .mockReturnValue({ closed: of(undefined) } as unknown as DialogRef<unknown, unknown>);
        const fixture = TestBed.createComponent(WebhookTriggersSectionComponent);
        fixture.detectChanges();
        httpMock.expectOne(LIST_URL).flush({ results: triggers });
        fixture.detectChanges();
        return { fixture, httpMock, access, open };
    }

    afterEach(() => TestBed.inject(HttpTestingController).verify());

    function editButton(fixture: ComponentFixture<WebhookTriggersSectionComponent>): HTMLButtonElement {
        return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[aria-label="Edit"]')!;
    }

    function pressEdit(fixture: ComponentFixture<WebhookTriggersSectionComponent>): void {
        editButton(fixture).click();
        fixture.detectChanges();
    }

    function answerUsageCheck({ fixture, httpMock }: EditSetup, usage: WebhookTriggerFlowsResponse = NOT_IN_USE): void {
        httpMock.expectOne(FLOWS_URL).flush(usage);
        fixture.detectChanges();
    }

    function failUsageCheck({ fixture, httpMock }: EditSetup, status: number): void {
        const request = httpMock.expectOne(FLOWS_URL);
        if (status === 0) {
            request.error(new ProgressEvent('error'));
        } else {
            request.flush({ detail: 'failed' }, { status, statusText: 'Failed' });
        }
        fixture.detectChanges();
    }

    function expectDialogOpened(
        open: ReturnType<typeof vi.spyOn>,
        readonly: boolean,
        trigger: WebhookTriggerModel = TRIGGER
    ): void {
        expect(open).toHaveBeenCalledExactlyOnceWith(
            WebhookTriggerDialogComponent,
            expect.objectContaining({
                data: { trigger: expect.objectContaining({ path: trigger.path, id: trigger.id }), readonly },
            })
        );
    }

    function expectEditDialogOpened(open: ReturnType<typeof vi.spyOn>, trigger: WebhookTriggerModel = TRIGGER): void {
        expectDialogOpened(open, false, trigger);
    }

    it('keeps Edit visible to a user who can update webhook triggers but not run flows', () => {
        const { fixture } = renderForEdit(false);

        expect(editButton(fixture)).not.toBeNull();
    });

    it('opens the edit dialog straight away for a user who can run flows, without asking which flows use it', () => {
        const { fixture, httpMock, open } = renderForEdit(true);

        pressEdit(fixture);

        expectEditDialogOpened(open);
        httpMock.expectNone(FLOWS_URL);
    });

    it('opens the edit dialog for a user who cannot run flows when no flow uses the trigger', () => {
        const setup = renderForEdit(false);

        pressEdit(setup.fixture);
        expect(setup.open).not.toHaveBeenCalled();
        answerUsageCheck(setup, NOT_IN_USE);

        expectEditDialogOpened(setup.open);
    });

    it('opens the dialog read-only for a user who cannot run flows when a flow uses the trigger', () => {
        const setup = renderForEdit(false);

        pressEdit(setup.fixture);
        answerUsageCheck(setup, IN_USE);

        expectDialogOpened(setup.open, true);
        expect(editButton(setup.fixture).disabled).toBe(false);
    });

    it('opens no dialog on a 403, which the forbidden interceptor already explained', () => {
        const setup = renderForEdit(false);

        pressEdit(setup.fixture);
        failUsageCheck(setup, 403);

        expect(setup.open).not.toHaveBeenCalled();
        setup.httpMock.expectNone(LIST_URL);
        expect(editButton(setup.fixture).disabled).toBe(false);
    });

    it('reloads the list instead of opening the edit dialog when the trigger is gone (404)', () => {
        const setup = renderForEdit(false);

        pressEdit(setup.fixture);
        failUsageCheck(setup, 404);
        setup.httpMock.expectOne(LIST_URL).flush({ results: [] });
        setup.fixture.detectChanges();

        expect(setup.open).not.toHaveBeenCalled();
        expect(editButton(setup.fixture)).toBeNull();
    });

    it.each([0, 500, 503])(
        'opens the edit dialog when the check fails with status %i; the backend still guards the save',
        (status) => {
            const setup = renderForEdit(false);

            pressEdit(setup.fixture);
            failUsageCheck(setup, status);

            expectEditDialogOpened(setup.open);
            expect(editButton(setup.fixture).disabled).toBe(false);
        }
    );

    it('asks only once when Edit is pressed again while the check is running', () => {
        const setup = renderForEdit(false);
        const button = editButton(setup.fixture);

        button.click();
        button.click();
        setup.fixture.detectChanges();

        expect(button.disabled).toBe(true);
        // expectOne fails if the second press sent a second request.
        answerUsageCheck(setup, NOT_IN_USE);

        expectEditDialogOpened(setup.open);
        expect(button.disabled).toBe(false);
    });

    it('checks again on the next press, reading the permission at that moment', () => {
        const setup = renderForEdit(false);

        pressEdit(setup.fixture);
        answerUsageCheck(setup, IN_USE);
        expectDialogOpened(setup.open, true);
        setup.open.mockClear();

        setup.access.canRunFlows = true;
        pressEdit(setup.fixture);

        expectEditDialogOpened(setup.open);
        setup.httpMock.expectNone(FLOWS_URL);
    });

    it('drops the check and opens nothing once the section is destroyed while the check is running', () => {
        const { fixture, httpMock, open } = renderForEdit(false);

        pressEdit(fixture);
        const request = httpMock.expectOne(FLOWS_URL);
        fixture.destroy();

        expect(request.cancelled).toBe(true);
        expect(open).not.toHaveBeenCalled();
    });

    it('opens the edit dialog without a check for a trigger that has no id', () => {
        const triggerWithoutId: WebhookTriggerModel = { ...TRIGGER, id: undefined };
        const { fixture, httpMock, open } = renderForEdit(false, [triggerWithoutId]);

        pressEdit(fixture);

        expectEditDialogOpened(open, triggerWithoutId);
        httpMock.expectNone(() => true);
    });
});

describe('WebhookTriggersSectionComponent "View Details" inside the Configure Models dialog', () => {
    function openHostDialog(): { dialog: Dialog; overlay: HTMLElement; tick: () => void } {
        configure(true, [TRIGGER]);
        const dialog = TestBed.inject(Dialog);
        const appRef = TestBed.inject(ApplicationRef);
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        dialog.open(WebhookTriggersSectionComponent);
        appRef.tick();
        return { dialog, overlay, tick: () => appRef.tick() };
    }

    it('closes only the menu on Escape, not the dialog hosting the section', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButtons(overlay)[0];

        trigger.click();
        tick();
        pressKey(viewDetailsItem(overlay)!, 'Escape', ESCAPE);
        tick();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(dialog.openDialogs).toHaveLength(1);
        expect(document.activeElement).toBe(trigger);
    });

    it('returns focus to the ⋮ button once the details dialog closes', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButtons(overlay)[0];

        trigger.click();
        tick();
        viewDetailsItem(overlay)!.click();
        tick();
        expect(dialog.openDialogs).toHaveLength(2);
        expect(trigger.contains(document.activeElement)).toBe(false);

        dialog.openDialogs[1].close();
        tick();

        expect(dialog.openDialogs).toHaveLength(1);
        expect(document.activeElement).toBe(trigger);
    });
});
