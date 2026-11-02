import { CdkMenu } from '@angular/cdk/menu';
import { DestroyRef, Directive, ElementRef, inject } from '@angular/core';

/**
 * A CDK menu closes on Tab and moves between its items only with the arrow keys.
 * With this directive Tab and Shift+Tab move between the items instead, wrapping
 * around at either end — the same as the app's other menus, which trap the focus.
 * Escape still closes the menu and returns the focus to its trigger.
 */
@Directive({
    selector: '[cdkMenu][appTabThroughMenu]',
})
export class TabThroughMenuDirective {
    private readonly menu = inject(CdkMenu);
    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;

    constructor() {
        const onKeydown = (event: KeyboardEvent): void => this.moveOnTab(event);
        // Capture phase: CdkMenu's own keydown listener on this element would close the menu first.
        this.host.addEventListener('keydown', onKeydown, { capture: true });
        inject(DestroyRef).onDestroy(() => this.host.removeEventListener('keydown', onKeydown, { capture: true }));
    }

    private moveOnTab(event: KeyboardEvent): void {
        if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return;
        const items = Array.from(this.host.querySelectorAll<HTMLElement>('.cdk-menu-item'));
        if (items.length === 0) return;
        event.preventDefault();
        event.stopPropagation();
        const currentIndex = items.findIndex((item) => item.contains(document.activeElement));
        const nextIndex = nextEnabledItemIndex(items, currentIndex, event.shiftKey ? -1 : 1);
        if (nextIndex === -1) return;
        // Goes through the menu's key manager, so the arrow keys carry on from the item Tab reached.
        // The index is into the full item list, disabled items included, as the key manager's is.
        this.menu.setActiveMenuItem(nextIndex);
    }
}

/** A disabled item stays in the menu but is no stop, as with the arrow keys. */
function isDisabledItem(item: HTMLElement): boolean {
    return item.getAttribute('aria-disabled') === 'true' || item.hasAttribute('disabled');
}

/**
 * The index of the next enabled item from `currentIndex` in the direction of `step`,
 * wrapping around; from no current item, the first (or last) enabled one. -1 when
 * every item is disabled.
 */
function nextEnabledItemIndex(items: readonly HTMLElement[], currentIndex: number, step: 1 | -1): number {
    const origin = currentIndex !== -1 ? currentIndex : step === 1 ? -1 : items.length;
    for (let offset = 1; offset <= items.length; offset++) {
        const index = (((origin + step * offset) % items.length) + items.length) % items.length;
        if (!isDisabledItem(items[index])) return index;
    }
    return -1;
}
