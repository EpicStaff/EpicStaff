import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatActionMenuComponent, ChatActionMenuItem } from './chat-action-menu.component';

@Component({
    imports: [ChatActionMenuComponent],
    template: `
        <button
            type="button"
            class="outside"
        >
            Elsewhere
        </button>
        <app-chat-action-menu
            label="Desk actions"
            icon="horizontal-dots"
            [items]="items()"
            (chosen)="onChosen($event)"
        />
    `,
})
class HostComponent {
    readonly items = signal<ChatActionMenuItem[]>([
        { id: 'settings', label: 'Settings' },
        { id: 'delete', label: 'Delete', disabled: true },
    ]);
    readonly chosen: { id: string; focused: Element | null }[] = [];

    onChosen(id: string): void {
        this.chosen.push({ id, focused: document.activeElement });
    }
}

describe('ChatActionMenuComponent', () => {
    let fixture: ComponentFixture<HostComponent>;

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const trigger = (): HTMLButtonElement => host().querySelector('.chat-action-menu__trigger') as HTMLButtonElement;
    const items = (): HTMLButtonElement[] =>
        Array.from(document.querySelectorAll<HTMLButtonElement>('.chat-action-menu__item'));

    function toggle(): void {
        trigger().click();
        fixture.detectChanges();
    }

    beforeEach(() => {
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
    });

    it('names its button, says whether it is open and lists the items, a disabled one disabled', () => {
        expect(trigger().getAttribute('aria-label')).toBe('Desk actions');
        expect(trigger().querySelector('use')?.getAttribute('href')).toBe('#icon-horizontal-dots');
        expect(trigger().getAttribute('aria-expanded')).toBe('false');
        expect(items()).toEqual([]);

        toggle();
        expect(trigger().getAttribute('aria-expanded')).toBe('true');
        expect(items().map((item) => item.textContent?.trim())).toEqual(['Settings', 'Delete']);
        expect(items().map((item) => item.disabled)).toEqual([false, true]);

        toggle();
        expect(items()).toEqual([]);
    });

    it('closes when an item is chosen, with the focus back on its button before the choice is announced', () => {
        toggle();
        items()[0].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.chosen).toEqual([{ id: 'settings', focused: trigger() }]);
        expect(items()).toEqual([]);
        expect(trigger().getAttribute('aria-expanded')).toBe('false');
    });

    it('closes on Escape and on a click outside, choosing nothing', () => {
        toggle();
        document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        fixture.detectChanges();
        expect(items()).toEqual([]);

        toggle();
        const outside = host().querySelector('.outside') as HTMLElement;
        outside.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
        outside.click();
        fixture.detectChanges();
        expect(items()).toEqual([]);
        expect(fixture.componentInstance.chosen).toEqual([]);
    });
});
