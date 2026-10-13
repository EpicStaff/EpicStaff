import { Dialog } from '@angular/cdk/dialog';
import { ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ApplicationRef } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';
import { WebhookTriggerModel } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { of, Subject } from 'rxjs';

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
