import { DOWN_ARROW, TAB } from '@angular/cdk/keycodes';
import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TabThroughMenuDirective } from './tab-through-menu.directive';

@Component({
    imports: [CdkMenu, CdkMenuItem, CdkMenuTrigger, TabThroughMenuDirective],
    template: `
        <button
            type="button"
            class="trigger"
            [cdkMenuTriggerFor]="menu"
        >
            Open
        </button>
        <ng-template #menu>
            <div
                cdkMenu
                appTabThroughMenu
            >
                <button
                    cdkMenuItem
                    type="button"
                >
                    One
                </button>
                <button
                    cdkMenuItem
                    type="button"
                >
                    Two
                </button>
                <button
                    cdkMenuItem
                    type="button"
                >
                    Three
                </button>
            </div>
        </ng-template>
    `,
})
class MenuHostComponent {}

@Component({
    imports: [CdkMenu, CdkMenuItem, CdkMenuTrigger, TabThroughMenuDirective],
    template: `
        <button
            type="button"
            class="trigger"
            [cdkMenuTriggerFor]="menu"
        >
            Open
        </button>
        <ng-template #menu>
            <div
                cdkMenu
                appTabThroughMenu
            >
                <button
                    cdkMenuItem
                    type="button"
                >
                    One
                </button>
                <button
                    cdkMenuItem
                    type="button"
                    [cdkMenuItemDisabled]="true"
                >
                    Two
                </button>
                <button
                    cdkMenuItem
                    type="button"
                >
                    Three
                </button>
            </div>
        </ng-template>
    `,
})
class MenuWithDisabledItemHostComponent {}

type Modifiers = Pick<KeyboardEventInit, 'shiftKey' | 'ctrlKey' | 'altKey' | 'metaKey'>;

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressTab(target: Element, modifiers: Modifiers = {}): KeyboardEvent {
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true, ...modifiers });
    Object.defineProperty(event, 'keyCode', { get: () => TAB });
    target.dispatchEvent(event);
    return event;
}

function menuItems(): HTMLButtonElement[] {
    return [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
}

function focusedLabel(): string | undefined {
    return document.activeElement?.textContent?.trim();
}

function openMenu(
    host: typeof MenuHostComponent | typeof MenuWithDisabledItemHostComponent = MenuHostComponent
): ComponentFixture<unknown> {
    const fixture = TestBed.createComponent<unknown>(host);
    fixture.detectChanges();
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.trigger')!.click();
    fixture.detectChanges();
    return fixture;
}

/** Focuses the item labelled `label` and presses Tab on it; returns the label focused afterwards. */
function tabFrom(fixture: ComponentFixture<unknown>, label: string, modifiers: Modifiers = {}) {
    const item = menuItems().find((menuItem) => menuItem.textContent?.trim() === label)!;
    item.focus();
    const event = pressTab(item, modifiers);
    fixture.detectChanges();
    return { event, focused: focusedLabel() };
}

describe('TabThroughMenuDirective', () => {
    it.each([
        { from: 'One', shiftKey: false, to: 'Two' },
        { from: 'Two', shiftKey: false, to: 'Three' },
        { from: 'Three', shiftKey: false, to: 'One' },
        { from: 'Three', shiftKey: true, to: 'Two' },
        { from: 'Two', shiftKey: true, to: 'One' },
        { from: 'One', shiftKey: true, to: 'Three' },
    ])(
        'moves the focus from $from to $to on Tab with shift $shiftKey and keeps the menu open',
        ({ from, shiftKey, to }) => {
            const fixture = openMenu();

            const { event, focused } = tabFrom(fixture, from, { shiftKey });

            expect(focused).toBe(to);
            expect(menuItems()).toHaveLength(3);
            expect(event.defaultPrevented).toBe(true);
        }
    );

    it.each([
        { from: 'One', shiftKey: false, to: 'Three' },
        { from: 'Three', shiftKey: true, to: 'One' },
    ])('passes over a disabled item from $from to $to with shift $shiftKey', ({ from, shiftKey, to }) => {
        const fixture = openMenu(MenuWithDisabledItemHostComponent);

        expect(tabFrom(fixture, from, { shiftKey }).focused).toBe(to);
    });

    it('lets the arrow keys carry on from the item Tab reached', () => {
        const fixture = openMenu();
        tabFrom(fixture, 'One');

        const down = new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true });
        Object.defineProperty(down, 'keyCode', { get: () => DOWN_ARROW });
        document.activeElement!.dispatchEvent(down);
        fixture.detectChanges();

        expect(focusedLabel()).toBe('Three');
    });

    it.each([{ ctrlKey: true }, { altKey: true }, { metaKey: true }])(
        'leaves Tab with %o to the browser',
        (modifiers) => {
            const fixture = openMenu();

            const { event, focused } = tabFrom(fixture, 'One', modifiers);

            expect(event.defaultPrevented).toBe(false);
            expect(focused).toBe('One');
            expect(menuItems()).toHaveLength(3);
        }
    );
});
