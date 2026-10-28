import { DOWN_ARROW, ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { BulkSelectDropdownComponent } from './bulk-select-dropdown.component';

/** Stands in for a list page: owns select mode and the selection, as the flows, versions and LLM pages do. */
@Component({
    imports: [BulkSelectDropdownComponent],
    template: `
        <app-bulk-select-dropdown
            [selectMode]="selectMode()"
            [selectedCount]="selectedCount()"
            [allSelected]="allSelected()"
            [disabled]="disabled()"
            [mod]="mod()"
            [appearance]="appearance()"
            (selectModeEntered)="onSelectModeEntered()"
            (selectAllToggled)="onSelectAllToggled()"
            (cleared)="onCleared()"
        />
    `,
})
class ListHostComponent {
    readonly selectMode = signal(false);
    readonly selectedCount = signal(0);
    readonly allSelected = signal(false);
    readonly disabled = signal(false);
    readonly mod = signal<'default' | 'small'>('default');
    readonly appearance = signal<'filled' | 'outline'>('filled');
    selectModeEnteredCount = 0;
    selectAllToggledCount = 0;
    clearedCount = 0;

    onSelectModeEntered(): void {
        this.selectModeEnteredCount += 1;
        this.selectMode.set(true);
    }

    onSelectAllToggled(): void {
        this.selectAllToggledCount += 1;
    }

    onCleared(): void {
        this.clearedCount += 1;
        this.selectMode.set(false);
        this.selectedCount.set(0);
    }
}

interface Rendered {
    fixture: ComponentFixture<ListHostComponent>;
    host: ListHostComponent;
    element: HTMLElement;
    overlay: HTMLElement;
}

function render(): Rendered {
    const fixture = TestBed.createComponent(ListHostComponent);
    fixture.detectChanges();
    return {
        fixture,
        host: fixture.componentInstance,
        element: fixture.nativeElement as HTMLElement,
        overlay: TestBed.inject(OverlayContainer).getContainerElement(),
    };
}

function mainButton(element: HTMLElement): HTMLButtonElement {
    return element.querySelector<HTMLButtonElement>('.bulk-select__main')!;
}

function clearButton(element: HTMLElement): HTMLButtonElement | null {
    return element.querySelector<HTMLButtonElement>('.bulk-select__clear');
}

function label(element: HTMLElement): string {
    return mainButton(element).textContent?.replace(/\s+/g, ' ').trim() ?? '';
}

function menuItem(overlay: HTMLElement): HTMLButtonElement | null {
    return overlay.querySelector<HTMLButtonElement>('[role="menuitem"]');
}

function isSelectedLook(element: HTMLElement): boolean {
    return element.querySelector('.bulk-select')!.classList.contains('bulk-select--selected');
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressKey(target: HTMLElement, key: string, keyCode: number): void {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => keyCode });
    target.dispatchEvent(event);
}

/** Clicks "Select": enters select mode and opens the menu. */
function clickSelect({ fixture, element }: Rendered): void {
    mainButton(element).click();
    fixture.detectChanges();
}

describe('BulkSelectDropdownComponent', () => {
    it('reads "Select" with a closed menu outside select mode', () => {
        const { element, overlay } = render();

        expect(label(element)).toBe('Select');
        expect(clearButton(element)).toBeNull();
        expect(isSelectedLook(element)).toBe(false);
        expect(mainButton(element).getAttribute('aria-haspopup')).toBe('menu');
        expect(mainButton(element).getAttribute('aria-expanded')).toBe('false');
        expect(menuItem(overlay)).toBeNull();
    });

    it('enters select mode and opens the "Select All" menu with one click on "Select"', () => {
        const rendered = render();
        const { host, element, overlay } = rendered;

        clickSelect(rendered);

        expect(host.selectModeEnteredCount).toBe(1);
        expect(host.selectMode()).toBe(true);
        expect(overlay.querySelector('[role="menu"]')).not.toBeNull();
        expect(menuItem(overlay)?.textContent?.trim()).toBe('Select All');
        expect(mainButton(element).getAttribute('aria-expanded')).toBe('true');
        expect(mainButton(element).getAttribute('aria-controls')).toBe(overlay.querySelector('[role="menu"]')!.id);
        // The "Pressed" look: still "Select", chevron flipped, no × while nothing is selected.
        expect(label(element)).toBe('Select');
        expect(element.querySelector('.bulk-select__chevron--open')).not.toBeNull();
        expect(clearButton(element)).toBeNull();
    });

    it('closes the menu and shows "Selected (N)" once an item is ticked', () => {
        const rendered = render();
        const { fixture, host, element, overlay } = rendered;
        clickSelect(rendered);

        host.selectedCount.set(2);
        fixture.detectChanges();

        expect(menuItem(overlay)).toBeNull();
        expect(mainButton(element).getAttribute('aria-expanded')).toBe('false');
        expect(label(element)).toBe('Selected (2)');
        expect(element.querySelector('.bulk-select__count')?.textContent?.trim()).toBe('(2)');
        expect(isSelectedLook(element)).toBe(true);
        expect(clearButton(element)).not.toBeNull();
    });

    it('shows "Selected (0)" when everything is unticked in select mode', () => {
        const rendered = render();
        const { fixture, host, element } = rendered;
        clickSelect(rendered);
        host.selectedCount.set(1);
        fixture.detectChanges();

        host.selectedCount.set(0);
        fixture.detectChanges();

        expect(label(element)).toBe('Selected (0)');
        expect(clearButton(element)).not.toBeNull();
    });

    it('keeps the × reachable when the menu is dismissed before anything is ticked', () => {
        const rendered = render();
        const { fixture, element, overlay } = rendered;
        clickSelect(rendered);

        document.body.click();
        fixture.detectChanges();

        expect(menuItem(overlay)).toBeNull();
        expect(label(element)).toBe('Selected (0)');
        expect(clearButton(element)).not.toBeNull();
    });

    it('keeps the "Selected (0)" look when the menu is reopened in select mode', () => {
        const rendered = render();
        const { fixture, element, overlay } = rendered;
        clickSelect(rendered);
        document.body.click();
        fixture.detectChanges();

        mainButton(element).click();
        fixture.detectChanges();

        // The "Selected_Pressed" look at 0: the control does not shrink back to "Select" under the cursor.
        expect(menuItem(overlay)).not.toBeNull();
        expect(label(element)).toBe('Selected (0)');
        expect(isSelectedLook(element)).toBe(true);
        expect(clearButton(element)).not.toBeNull();
        expect(element.querySelector('.bulk-select__chevron--open')).not.toBeNull();
    });

    it('toggles the menu from the label in select mode without entering it again', () => {
        const rendered = render();
        const { fixture, host, element, overlay } = rendered;
        clickSelect(rendered);
        host.selectedCount.set(3);
        fixture.detectChanges();

        mainButton(element).click();
        fixture.detectChanges();
        expect(menuItem(overlay)).not.toBeNull();
        // The "Selected_Pressed" look.
        expect(label(element)).toBe('Selected (3)');
        expect(element.querySelector('.bulk-select__chevron--open')).not.toBeNull();

        mainButton(element).click();
        fixture.detectChanges();
        expect(menuItem(overlay)).toBeNull();
        expect(host.selectModeEnteredCount).toBe(1);
    });

    it('reports "Select All" and reads "Deselect All" when everything is selected', () => {
        const rendered = render();
        const { fixture, host, overlay } = rendered;
        clickSelect(rendered);

        menuItem(overlay)!.click();
        fixture.detectChanges();
        expect(host.selectAllToggledCount).toBe(1);
        expect(menuItem(overlay)).toBeNull();

        host.selectedCount.set(4);
        host.allSelected.set(true);
        fixture.detectChanges();
        clickSelect(rendered);

        expect(menuItem(overlay)?.textContent?.trim()).toBe('Deselect All');
    });

    it('clears the selection and leaves select mode with the ×, keeping focus on the control', () => {
        const rendered = render();
        const { fixture, host, element } = rendered;
        clickSelect(rendered);
        host.selectedCount.set(2);
        fixture.detectChanges();
        clearButton(element)!.focus();

        clearButton(element)!.click();
        fixture.detectChanges();

        expect(host.clearedCount).toBe(1);
        expect(label(element)).toBe('Select');
        expect(clearButton(element)).toBeNull();
        // The × is gone; focus must not fall back to <body>.
        expect(document.activeElement).toBe(mainButton(element));
    });

    it('closes the menu when select mode ends', () => {
        const rendered = render();
        const { fixture, host, overlay } = rendered;
        clickSelect(rendered);

        host.selectMode.set(false);
        fixture.detectChanges();

        expect(menuItem(overlay)).toBeNull();
    });

    it('closes on Escape, returns focus to the button, and keeps the Escape inside the menu', () => {
        const rendered = render();
        const { fixture, element, overlay } = rendered;
        clickSelect(rendered);
        // Stands in for an overlay below (a dialog hosting the list), which would close on an Escape reaching it.
        const escapesPastMenu: KeyboardEvent[] = [];
        const recordEscape = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') escapesPastMenu.push(event);
        };
        overlay.addEventListener('keydown', recordEscape);

        pressKey(menuItem(overlay)!, 'Escape', ESCAPE);
        fixture.detectChanges();
        overlay.removeEventListener('keydown', recordEscape);

        expect(menuItem(overlay)).toBeNull();
        expect(document.activeElement).toBe(mainButton(element));
        expect(escapesPastMenu).toEqual([]);
    });

    it('opens from the keyboard, entering select mode and focusing "Select All"', () => {
        const { fixture, host, element, overlay } = render();
        mainButton(element).focus();

        pressKey(mainButton(element), 'ArrowDown', DOWN_ARROW);
        fixture.detectChanges();

        expect(host.selectMode()).toBe(true);
        expect(document.activeElement).toBe(menuItem(overlay));
    });

    it('disables both buttons while the host is busy', () => {
        const rendered = render();
        const { fixture, host, element } = rendered;
        clickSelect(rendered);
        host.selectedCount.set(1);
        host.disabled.set(true);
        fixture.detectChanges();

        expect(mainButton(element).disabled).toBe(true);
        expect(clearButton(element)!.disabled).toBe(true);
    });

    function controlClasses(element: HTMLElement): DOMTokenList {
        return element.querySelector('.bulk-select')!.classList;
    }

    function menuClasses(overlay: HTMLElement): DOMTokenList {
        return overlay.querySelector('.bulk-select-menu')!.classList;
    }

    describe('size', () => {
        it('is the default size, control and menu, unless told otherwise', () => {
            const rendered = render();
            const { element, overlay } = rendered;

            expect(controlClasses(element)).not.toContain('bulk-select--small');
            clickSelect(rendered);
            expect(menuClasses(overlay)).not.toContain('bulk-select-menu--small');
        });

        it('switches control and menu to the small size with mod="small"', () => {
            const rendered = render();
            const { fixture, host, element, overlay } = rendered;

            host.mod.set('small');
            fixture.detectChanges();

            expect(controlClasses(element)).toContain('bulk-select--small');
            clickSelect(rendered);
            expect(menuClasses(overlay)).toContain('bulk-select-menu--small');
        });
    });

    describe('appearance', () => {
        it('is filled, control and menu, unless told otherwise', () => {
            const rendered = render();
            const { element, overlay } = rendered;

            expect(controlClasses(element)).not.toContain('bulk-select--outline');
            clickSelect(rendered);
            expect(menuClasses(overlay)).not.toContain('bulk-select-menu--outline');
        });

        it('switches control and menu to the outline look with appearance="outline"', () => {
            const rendered = render();
            const { fixture, host, element, overlay } = rendered;

            host.appearance.set('outline');
            fixture.detectChanges();

            expect(controlClasses(element)).toContain('bulk-select--outline');
            clickSelect(rendered);
            expect(menuClasses(overlay)).toContain('bulk-select-menu--outline');
        });
    });

    it('marks the main segment open while the menu is open', () => {
        const rendered = render();
        const { fixture, element } = rendered;

        clickSelect(rendered);
        expect(mainButton(element).classList).toContain('bulk-select__main--open');

        document.body.click();
        fixture.detectChanges();
        expect(mainButton(element).classList).not.toContain('bulk-select__main--open');
    });
});
