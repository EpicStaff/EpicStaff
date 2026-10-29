import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { ExplorerContextMenuComponent } from './explorer-context-menu.component';
import { ExplorerMenuItem } from './explorer-menu.model';

function item(label: string, extra: Partial<ExplorerMenuItem> = {}): ExplorerMenuItem {
    return { id: label.toLowerCase(), label, resource: ResourceCode.Agents, action: ActionCode.Update, ...extra };
}

const ITEMS: ExplorerMenuItem[] = [
    item('Duplicate', { disabled: true }),
    item('Rename'),
    item('Color', { children: [item('Blue'), item('Green')] }),
    item('Delete'),
];

// The CDK key manager reads `keyCode`, which a synthetic KeyboardEvent leaves at 0.
const KEY_CODES: Record<string, number> = { ArrowDown: 40, ArrowUp: 38, Home: 36, End: 35, Escape: 27 };

function press(key: string, target: Element = document.activeElement ?? document.body): void {
    const event = new KeyboardEvent('keydown', { key, bubbles: true });
    Object.defineProperty(event, 'keyCode', { get: () => KEY_CODES[key] ?? 0 });
    target.dispatchEvent(event);
}

function openMenu(): { fixture: ComponentFixture<ExplorerContextMenuComponent>; closes: () => number } {
    const fixture = TestBed.createComponent(ExplorerContextMenuComponent);
    let closeCount = 0;
    fixture.componentInstance.close.subscribe(() => closeCount++);
    fixture.componentRef.setInput('position', { x: 10, y: 10 });
    fixture.componentRef.setInput('items', ITEMS);
    fixture.componentRef.setInput('open', true);
    settle(fixture);
    return { fixture, closes: () => closeCount };
}

/** Renders and runs after-render work, where the menu moves focus. */
function settle(fixture: ComponentFixture<ExplorerContextMenuComponent>): void {
    fixture.detectChanges();
    TestBed.tick();
}

const focusedLabel = (): string | undefined => document.activeElement?.textContent?.trim();

function row(fixture: ComponentFixture<ExplorerContextMenuComponent>, label: string): HTMLButtonElement {
    const rows = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
    return Array.from(rows).find((candidate) => candidate.textContent?.trim() === label)!;
}

describe('ExplorerContextMenuComponent keyboard', () => {
    it('focuses the first enabled item on open', () => {
        openMenu();

        expect(focusedLabel()).toBe('Rename');
    });

    it.each([
        { keys: ['ArrowDown'], focused: 'Color' },
        { keys: ['ArrowDown', 'ArrowDown'], focused: 'Delete' },
        { keys: ['ArrowDown', 'ArrowDown', 'ArrowDown'], focused: 'Rename' },
        { keys: ['ArrowUp'], focused: 'Delete' },
        { keys: ['End', 'Home'], focused: 'Rename' },
    ])('from the first item, $keys moves focus to "$focused", skipping the disabled one', ({ keys, focused }) => {
        openMenu();

        for (const key of keys) press(key);

        expect(focusedLabel()).toBe(focused);
    });

    it('walks an expanded sub-list in place, between its row and the next one', () => {
        const { fixture } = openMenu();
        row(fixture, 'Color').focus();

        row(fixture, 'Color').click();
        settle(fixture);
        const walked: (string | undefined)[] = [];
        for (const key of ['ArrowDown', 'ArrowDown', 'ArrowDown']) {
            press(key);
            walked.push(focusedLabel());
        }

        expect(walked).toEqual(['Blue', 'Green', 'Delete']);
    });

    it('marks the expandable row expanded and labels its nested rows as a group of menu items', () => {
        const { fixture } = openMenu();

        row(fixture, 'Color').click();
        settle(fixture);

        const group = (fixture.nativeElement as HTMLElement).querySelector('[role="group"]')!;
        const nestedLabels = Array.from(group.querySelectorAll('[role="menuitem"]')).map((element) =>
            element.textContent?.trim()
        );
        expect(row(fixture, 'Color').getAttribute('aria-expanded')).toBe('true');
        expect(row(fixture, 'Color').getAttribute('aria-haspopup')).toBeNull();
        expect(group.getAttribute('aria-label')).toBe('Color');
        expect(nestedLabels).toEqual(['Blue', 'Green']);
    });

    it.each([
        { from: 'an item', target: () => document.activeElement! },
        { from: 'outside the menu, e.g. the ⋮ that opened it', target: () => document.body },
    ])('Escape from $from closes the menu', ({ target }) => {
        const { closes } = openMenu();

        press('Escape', target());

        expect(closes()).toBe(1);
    });
});
