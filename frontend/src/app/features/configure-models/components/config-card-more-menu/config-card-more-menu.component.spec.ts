import { Dialog } from '@angular/cdk/dialog';
import { DOWN_ARROW, ENTER, ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ApplicationRef, Component, inject } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService, AuthorshipDetailsSource } from '@shared/components';

import { ConfigCardMoreMenuComponent } from './config-card-more-menu.component';

function render(): {
    fixture: ComponentFixture<ConfigCardMoreMenuComponent>;
    overlay: HTMLElement;
    emitted: HTMLElement[];
} {
    const fixture = TestBed.createComponent(ConfigCardMoreMenuComponent);
    const emitted: HTMLElement[] = [];
    fixture.componentInstance.viewDetailsClick.subscribe((trigger) => emitted.push(trigger));
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, overlay, emitted };
}

function moreButton(host: HTMLElement): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>('[aria-label="More actions"]')!;
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

describe('ConfigCardMoreMenuComponent', () => {
    it('opens on click with the trigger marked active and focus on "View Details"', () => {
        const { fixture, overlay } = render();
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();

        expect(trigger.classList).toContain('more-menu__trigger--active');
        expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
        expect(trigger.getAttribute('aria-expanded')).toBe('true');
        expect(overlay.querySelector('[role="menu"]')).not.toBeNull();
        expect(overlay.querySelectorAll('[role="menuitem"]')).toHaveLength(1);
        expect(viewDetailsItem(overlay)?.textContent?.trim()).toBe('View Details');
        expect(document.activeElement).toBe(viewDetailsItem(overlay));
    });

    it('emits viewDetailsClick with its trigger, and closes the menu, when "View Details" is chosen', () => {
        const { fixture, overlay, emitted } = render();
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        // The host closes the details dialog back to `trigger`: the focused menu item dies with the menu.
        expect(emitted).toEqual([trigger]);
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('more-menu__trigger--active');
        expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });

    it('closes when the trigger is clicked again', () => {
        const { fixture, overlay } = render();
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        trigger.click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('more-menu__trigger--active');
    });

    it('closes on a click outside the menu', () => {
        const { fixture, overlay } = render();

        moreButton(fixture.nativeElement).click();
        fixture.detectChanges();
        document.body.click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
    });

    it('can be opened and "View Details" chosen with the keyboard alone', () => {
        const { fixture, overlay, emitted } = render();
        const trigger = moreButton(fixture.nativeElement);
        trigger.focus();

        pressKey(trigger, 'ArrowDown', DOWN_ARROW);
        fixture.detectChanges();

        const item = viewDetailsItem(overlay)!;
        expect(document.activeElement).toBe(item);

        pressKey(item, 'Enter', ENTER);
        fixture.detectChanges();

        expect(emitted).toEqual([trigger]);
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(document.activeElement).toBe(trigger);
    });

    it('closes on Escape and returns focus to the trigger', () => {
        const { fixture, overlay, emitted } = render();
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        pressKey(viewDetailsItem(overlay)!, 'Escape', ESCAPE);
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('more-menu__trigger--active');
        expect(document.activeElement).toBe(trigger);
        expect(emitted).toEqual([]);
    });
});

const AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    created_at: '2026-03-12T13:28:23Z',
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-03-13T09:00:00Z',
};

/** Stands in for the Configure Models dialog: hosts the menu and opens details the way the cards' hosts do. */
@Component({
    imports: [ConfigCardMoreMenuComponent],
    template: `<app-config-card-more-menu (viewDetailsClick)="openDetails($event)" />`,
})
class MenuInDialogHostComponent {
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);

    protected openDetails(trigger: HTMLElement): void {
        this.authorshipDetailsDialog.open('Configuration Details', AUTHORSHIP, trigger);
    }
}

describe('ConfigCardMoreMenuComponent inside a dialog', () => {
    function openHostDialog(): { dialog: Dialog; overlay: HTMLElement; tick: () => void } {
        const dialog = TestBed.inject(Dialog);
        const appRef = TestBed.inject(ApplicationRef);
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        dialog.open(MenuInDialogHostComponent);
        appRef.tick();
        return { dialog, overlay, tick: () => appRef.tick() };
    }

    it('closes only the menu on Escape, not the dialog hosting it', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButton(overlay);

        trigger.click();
        tick();
        pressKey(viewDetailsItem(overlay)!, 'Escape', ESCAPE);
        tick();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(dialog.openDialogs).toHaveLength(1);
        expect(document.activeElement).toBe(trigger);
    });

    it('returns focus to the trigger, inside the hosting dialog, once the details dialog closes', () => {
        const { dialog, overlay, tick } = openHostDialog();
        const trigger = moreButton(overlay);

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
