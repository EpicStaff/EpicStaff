import { Dialog } from '@angular/cdk/dialog';
import { DOWN_ARROW, ENTER, ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { ApplicationRef, Component, inject } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService, AuthorshipDetailsSource } from '@shared/components';
import { LlmLibraryModel, ModelTypes } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { LlmLibraryCardComponent, LlmLibraryCardViewDetailsEvent } from './llm-library-card.component';

const MODEL: LlmLibraryModel = {
    id: 7,
    customName: 'gpt-4.1-chat',
    modelName: 'gpt-4.1',
    tags: [],
    temperature: 0.7,
    usedByCount: null,
    configType: ModelTypes.LLM,
    isDeprecated: false,
};

function configure(canWrite: boolean): void {
    TestBed.configureTestingModule({
        providers: [{ provide: PermissionsService, useValue: { can: () => canWrite } }],
    });
}

function render(canWrite: boolean): {
    fixture: ComponentFixture<LlmLibraryCardComponent>;
    overlay: HTMLElement;
    emitted: LlmLibraryCardViewDetailsEvent[];
} {
    configure(canWrite);
    const fixture = TestBed.createComponent(LlmLibraryCardComponent);
    fixture.componentRef.setInput('model', MODEL);
    const emitted: LlmLibraryCardViewDetailsEvent[] = [];
    fixture.componentInstance.viewDetailsClick.subscribe((event) => emitted.push(event));
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

describe('LlmLibraryCardComponent more menu', () => {
    it('opens on click with the trigger marked active and focus on "View Details"', () => {
        const { fixture, overlay } = render(true);
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();

        expect(trigger.classList).toContain('llm-card__action--active');
        expect(trigger.getAttribute('aria-haspopup')).toBe('menu');
        expect(trigger.getAttribute('aria-expanded')).toBe('true');
        expect(overlay.querySelector('[role="menu"]')).not.toBeNull();
        expect(viewDetailsItem(overlay)?.textContent?.trim()).toBe('View Details');
        expect(document.activeElement).toBe(viewDetailsItem(overlay));
    });

    it('emits viewDetailsClick with the model and its trigger, and closes the menu, when "View Details" is chosen', () => {
        const { fixture, overlay, emitted } = render(true);
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        // The host closes the details dialog back to `trigger`: the focused menu item dies with the menu.
        expect(emitted).toEqual([{ model: MODEL, trigger }]);
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('llm-card__action--active');
        expect(trigger.getAttribute('aria-expanded')).toBe('false');
    });

    it('offers "View Details" to a user who can only read configurations', () => {
        const { fixture, overlay } = render(false);
        const host = fixture.nativeElement as HTMLElement;

        expect(host.querySelectorAll('.llm-card__action')).toHaveLength(1);
        moreButton(host).click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).not.toBeNull();
    });

    it('closes when the trigger is clicked again', () => {
        const { fixture, overlay } = render(true);
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        trigger.click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('llm-card__action--active');
    });

    it('closes on a click outside the menu', () => {
        const { fixture, overlay } = render(true);

        moreButton(fixture.nativeElement).click();
        fixture.detectChanges();
        document.body.click();
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
    });

    it('can be opened and "View Details" chosen with the keyboard alone', () => {
        const { fixture, overlay, emitted } = render(true);
        const trigger = moreButton(fixture.nativeElement);
        trigger.focus();

        pressKey(trigger, 'ArrowDown', DOWN_ARROW);
        fixture.detectChanges();

        const item = viewDetailsItem(overlay)!;
        expect(document.activeElement).toBe(item);

        pressKey(item, 'Enter', ENTER);
        fixture.detectChanges();

        expect(emitted).toEqual([{ model: MODEL, trigger }]);
        expect(viewDetailsItem(overlay)).toBeNull();
        expect(document.activeElement).toBe(trigger);
    });

    it('closes on Escape and returns focus to the trigger', () => {
        const { fixture, overlay, emitted } = render(true);
        const trigger = moreButton(fixture.nativeElement);

        trigger.click();
        fixture.detectChanges();
        pressKey(viewDetailsItem(overlay)!, 'Escape', ESCAPE);
        fixture.detectChanges();

        expect(viewDetailsItem(overlay)).toBeNull();
        expect(trigger.classList).not.toContain('llm-card__action--active');
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

/** Stands in for the Configure Models dialog: hosts a card and opens its details the way the section does. */
@Component({
    imports: [LlmLibraryCardComponent],
    template: `<app-llm-library-card
        [model]="model"
        (viewDetailsClick)="openDetails($event)"
    />`,
})
class CardInDialogHostComponent {
    protected readonly model = MODEL;
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);

    protected openDetails({ trigger }: LlmLibraryCardViewDetailsEvent): void {
        this.authorshipDetailsDialog.open('Configuration Details', AUTHORSHIP, trigger);
    }
}

describe('LlmLibraryCardComponent more menu inside a dialog', () => {
    function openHostDialog(): { dialog: Dialog; overlay: HTMLElement; tick: () => void } {
        configure(true);
        const dialog = TestBed.inject(Dialog);
        const appRef = TestBed.inject(ApplicationRef);
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        dialog.open(CardInDialogHostComponent);
        appRef.tick();
        return { dialog, overlay, tick: () => appRef.tick() };
    }

    it('closes only the menu on Escape, not the dialog hosting the card', () => {
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
