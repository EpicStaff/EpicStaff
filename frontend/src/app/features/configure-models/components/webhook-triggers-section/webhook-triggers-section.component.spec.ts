import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { ApplicationRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    AuthorshipDetailsDialogService,
    ConfirmationDialogService,
    WebhookTriggerDialogComponent,
} from '@shared/components';
import { ActionCode, ResourceCode, WebhookTriggerFlowsResponse, WebhookTriggerModel } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
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

        expect(Array.from(actions, (action) => action.getAttribute('title'))).toEqual(['More', 'Edit', 'Delete']);
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
    interface EditSetup {
        fixture: ComponentFixture<WebhookTriggersSectionComponent>;
        /** Read by the mocked `can()` on every call, so a test can grant FLOWS:RUN between presses. */
        access: { canRunFlows: boolean };
        list: ReturnType<typeof vi.fn>;
        getFlows: ReturnType<typeof vi.fn>;
        confirm: ReturnType<typeof vi.fn>;
        open: ReturnType<typeof vi.spyOn>;
    }

    const NOT_IN_USE: WebhookTriggerFlowsResponse = { flow_count: 0, flows: [] };
    const IN_USE: WebhookTriggerFlowsResponse = { flow_count: 1, flows: [{ id: 9, name: 'Orders' }] };

    function renderForEdit(
        canRunFlows: boolean,
        flows$: Observable<WebhookTriggerFlowsResponse> = of(NOT_IN_USE),
        triggers: WebhookTriggerModel[] = [TRIGGER]
    ): EditSetup {
        const access = { canRunFlows };
        const list = vi.fn(() => of(triggers));
        const getFlows = vi.fn(() => flows$);
        const confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: WebhookTriggerService, useValue: { list, changed$: new Subject<void>(), getFlows } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: ToastService, useValue: {} },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Flows && action === ActionCode.Run ? access.canRunFlows : true,
                    },
                },
            ],
        });
        const open = vi
            .spyOn(TestBed.inject(Dialog), 'open')
            .mockReturnValue({ closed: of(undefined) } as unknown as DialogRef<unknown, unknown>);
        const fixture = TestBed.createComponent(WebhookTriggersSectionComponent);
        fixture.detectChanges();
        return { fixture, access, list, getFlows, confirm, open };
    }

    function editButton(fixture: ComponentFixture<WebhookTriggersSectionComponent>): HTMLButtonElement {
        return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[title="Edit"]')!;
    }

    function pressEdit(fixture: ComponentFixture<WebhookTriggersSectionComponent>): void {
        editButton(fixture).click();
        fixture.detectChanges();
    }

    function expectEditDialogOpened(open: ReturnType<typeof vi.spyOn>, trigger: WebhookTriggerModel = TRIGGER): void {
        expect(open).toHaveBeenCalledExactlyOnceWith(
            WebhookTriggerDialogComponent,
            expect.objectContaining({
                data: { trigger: expect.objectContaining({ path: trigger.path, id: trigger.id }) },
            })
        );
    }

    it('keeps Edit visible to a user who can update webhook triggers but not run flows', () => {
        const { fixture } = renderForEdit(false);

        expect(editButton(fixture)).not.toBeNull();
    });

    it('opens the edit dialog straight away for a user who can run flows, without asking which flows use it', () => {
        const { fixture, getFlows, confirm, open } = renderForEdit(true);

        pressEdit(fixture);

        expectEditDialogOpened(open);
        expect(getFlows).not.toHaveBeenCalled();
        expect(confirm).not.toHaveBeenCalled();
    });

    it('opens the edit dialog for a user who cannot run flows when no flow uses the trigger', () => {
        const { fixture, getFlows, confirm, open } = renderForEdit(false);

        pressEdit(fixture);

        expect(getFlows).toHaveBeenCalledExactlyOnceWith(TRIGGER.id);
        expectEditDialogOpened(open);
        expect(confirm).not.toHaveBeenCalled();
    });

    // The wording for every usage is covered in the edit-permission service spec.
    it('shows the Run permission warning instead of the edit dialog when a flow uses the trigger', () => {
        const { fixture, confirm, open } = renderForEdit(false, of(IN_USE));

        pressEdit(fixture);

        expect(confirm).toHaveBeenCalledExactlyOnceWith({
            title: 'Run permission required',
            message: 'This webhook is part of the flow <strong>Orders</strong>.',
            caution:
                "You can't <strong>edit</strong> it because you don't have the <strong>Run</strong> permission on flows.",
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
        expect(open).not.toHaveBeenCalled();
        expect(editButton(fixture).disabled).toBe(false);
    });

    it('opens neither dialog on a 403, which the forbidden interceptor already explained', () => {
        const { fixture, confirm, open, list } = renderForEdit(
            false,
            throwError(() => new HttpErrorResponse({ status: 403 }))
        );

        pressEdit(fixture);

        expect(open).not.toHaveBeenCalled();
        expect(confirm).not.toHaveBeenCalled();
        expect(list).toHaveBeenCalledTimes(1);
        expect(editButton(fixture).disabled).toBe(false);
    });

    it('reloads the list instead of opening the edit dialog when the trigger is gone (404)', () => {
        const { fixture, confirm, open, list } = renderForEdit(
            false,
            throwError(() => new HttpErrorResponse({ status: 404 }))
        );

        pressEdit(fixture);

        expect(open).not.toHaveBeenCalled();
        expect(confirm).not.toHaveBeenCalled();
        expect(list).toHaveBeenCalledTimes(2);
    });

    it.each([0, 500, 503])(
        'opens the edit dialog when the check fails with status %i; the backend still guards the save',
        (status) => {
            const { fixture, confirm, open } = renderForEdit(
                false,
                throwError(() => new HttpErrorResponse({ status }))
            );

            pressEdit(fixture);

            expectEditDialogOpened(open);
            expect(confirm).not.toHaveBeenCalled();
            expect(editButton(fixture).disabled).toBe(false);
        }
    );

    it('asks only once when Edit is pressed again while the check is running', () => {
        const response$ = new Subject<WebhookTriggerFlowsResponse>();
        const { fixture, getFlows, open } = renderForEdit(false, response$);
        const button = editButton(fixture);

        button.click();
        button.click();
        fixture.detectChanges();

        expect(getFlows).toHaveBeenCalledTimes(1);
        expect(button.disabled).toBe(true);

        response$.next(NOT_IN_USE);
        response$.complete();
        fixture.detectChanges();

        expectEditDialogOpened(open);
        expect(button.disabled).toBe(false);
    });

    it('checks again on the next press, reading the permission at that moment', () => {
        const { fixture, access, getFlows, confirm, open } = renderForEdit(false, of(IN_USE));

        pressEdit(fixture);
        expect(confirm).toHaveBeenCalledTimes(1);
        expect(open).not.toHaveBeenCalled();

        pressEdit(fixture);
        expect(getFlows).toHaveBeenCalledTimes(2);
        expect(confirm).toHaveBeenCalledTimes(2);

        access.canRunFlows = true;
        pressEdit(fixture);

        expectEditDialogOpened(open);
        expect(getFlows).toHaveBeenCalledTimes(2);
        expect(confirm).toHaveBeenCalledTimes(2);
    });

    it('opens nothing once the section is destroyed while the check is running', () => {
        const response$ = new Subject<WebhookTriggerFlowsResponse>();
        const { fixture, confirm, open } = renderForEdit(false, response$);

        pressEdit(fixture);
        fixture.destroy();

        expect(() => {
            response$.next(IN_USE);
            response$.complete();
        }).not.toThrow();
        expect(response$.observed).toBe(false);
        expect(confirm).not.toHaveBeenCalled();
        expect(open).not.toHaveBeenCalled();
    });

    it('opens the edit dialog without a check for a trigger that has no id', () => {
        const triggerWithoutId: WebhookTriggerModel = { ...TRIGGER, id: undefined };
        const { fixture, getFlows, open } = renderForEdit(false, of(IN_USE), [triggerWithoutId]);

        pressEdit(fixture);

        expectEditDialogOpened(open, triggerWithoutId);
        expect(getFlows).not.toHaveBeenCalled();
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
