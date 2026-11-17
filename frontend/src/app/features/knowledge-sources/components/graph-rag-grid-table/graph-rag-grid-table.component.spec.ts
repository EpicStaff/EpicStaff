// Pins the grid table's DOM behaviour: grid semantics, roving-tabindex keyboard navigation, the cell popover,
// search highlighting and the action-button column. Component layer (rendered in a host, driven through DOM events).
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GraphRagGridTableComponent } from './graph-rag-grid-table.component';
import { GraphGridActionEvent, GraphGridColumnDef } from './graph-rag-grid-table.model';

const COLUMN_DEFS: GraphGridColumnDef[] = [{ key: 'title' }, { key: 'description' }];
const ROWS: Record<string, unknown>[] = [
    { title: 'Entity 1', description: 'A long description of the first entity' },
    { title: 'Entity 2', description: null },
];
const THIRD_ROW: Record<string, unknown> = { title: 'Entity 3', description: 'Third' };

const COLUMN_DEFS_WITH_ACTION: GraphGridColumnDef[] = [
    { key: 'title' },
    { key: 'description' },
    { key: 'actions', pinned: 'end', width: '48px', action: { name: 'view', icon: 'eye' } },
];

@Component({
    template: `
        <app-graph-rag-grid-table
            [columnDefs]="columnDefs()"
            [rows]="rows()"
            [searchTerm]="searchTerm()"
            (actionClick)="actions.push($event)"
        />
    `,
    imports: [GraphRagGridTableComponent],
})
class TestHostComponent {
    readonly columnDefs = signal(COLUMN_DEFS);
    readonly rows = signal(ROWS);
    readonly searchTerm = signal('');
    readonly actions: GraphGridActionEvent[] = [];
}

describe('GraphRagGridTableComponent', () => {
    let fixture: ComponentFixture<TestHostComponent>;
    let host: HTMLElement;

    function bodyCells(): HTMLElement[] {
        return Array.from(host.querySelectorAll<HTMLElement>('[role="gridcell"]'));
    }

    function popover(): HTMLElement | null {
        return host.querySelector<HTMLElement>('.grid-table-popover');
    }

    function pressKey(target: EventTarget, key: string): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    beforeEach(async () => {
        await TestBed.configureTestingModule({ imports: [TestHostComponent] }).compileComponents();
        fixture = TestBed.createComponent(TestHostComponent);
        host = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    function tabStops(): HTMLElement[] {
        return bodyCells().filter((cell) => cell.tabIndex === 0);
    }

    it('exposes grid semantics with a single tab stop on the first body cell', () => {
        expect(host.querySelector('[role="grid"]')).not.toBeNull();
        const headers = Array.from(host.querySelectorAll('[role="columnheader"]')).map((header) =>
            header.textContent?.trim()
        );
        expect(headers).toEqual(['Title', 'Description']);
        // One header row plus one row per data row
        expect(host.querySelectorAll('[role="row"]').length).toBe(ROWS.length + 1);
        expect(bodyCells().length).toBe(ROWS.length * COLUMN_DEFS.length);
        expect(tabStops()).toEqual([bodyCells()[0]]);
        expect(
            bodyCells()
                .slice(1)
                .every((cell) => cell.tabIndex === -1)
        ).toBe(true);
    });

    it('moves focus and the tab stop between cells with the arrow keys and stops at the edges', () => {
        // Cells in DOM order: [0] row 1 title, [1] row 1 description, [2] row 2 title, [3] row 2 description.
        bodyCells()[0].focus();

        const right = pressKey(document.activeElement!, 'ArrowRight');
        expect(document.activeElement).toBe(bodyCells()[1]);
        expect(right.defaultPrevented).toBe(true);

        pressKey(document.activeElement!, 'ArrowDown');
        expect(document.activeElement).toBe(bodyCells()[3]);

        pressKey(document.activeElement!, 'ArrowDown');
        pressKey(document.activeElement!, 'ArrowRight');
        expect(document.activeElement).toBe(bodyCells()[3]);

        pressKey(document.activeElement!, 'ArrowLeft');
        expect(document.activeElement).toBe(bodyCells()[2]);

        pressKey(document.activeElement!, 'ArrowUp');
        expect(document.activeElement).toBe(bodyCells()[0]);

        pressKey(document.activeElement!, 'ArrowUp');
        pressKey(document.activeElement!, 'ArrowLeft');
        expect(document.activeElement).toBe(bodyCells()[0]);
        expect(tabStops()).toEqual([bodyCells()[0]]);
    });

    it('jumps to the first and last cell of the row with Home and End', () => {
        bodyCells()[2].focus();

        pressKey(document.activeElement!, 'End');
        expect(document.activeElement).toBe(bodyCells()[3]);

        pressKey(document.activeElement!, 'Home');
        expect(document.activeElement).toBe(bodyCells()[2]);
        expect(tabStops()).toEqual([bodyCells()[2]]);
    });

    it('moves the tab stop to a cell focused by a click', () => {
        bodyCells()[3].focus();
        fixture.detectChanges();

        expect(tabStops()).toEqual([bodyCells()[3]]);
    });

    it('keeps exactly one tab stop when the rows shrink below the active cell', () => {
        fixture.componentInstance.rows.set([...ROWS, THIRD_ROW]);
        fixture.detectChanges();
        bodyCells()[5].focus();
        fixture.detectChanges();

        fixture.componentInstance.rows.set([ROWS[0]]);
        fixture.detectChanges();

        expect(tabStops()).toEqual([bodyCells()[1]]);
    });

    it('closes the open popover when the arrow keys move to another cell', () => {
        bodyCells()[0].focus();
        pressKey(document.activeElement!, 'Enter');
        expect(popover()).not.toBeNull();

        pressKey(document.activeElement!, 'ArrowRight');

        expect(popover()).toBeNull();
        expect(document.activeElement).toBe(bodyCells()[1]);
    });

    it('opens the popover with Enter on a cell reached with the arrow keys', () => {
        bodyCells()[0].focus();
        pressKey(document.activeElement!, 'ArrowRight');

        pressKey(document.activeElement!, 'Enter');

        expect(popover()?.textContent?.trim()).toBe('A long description of the first entity');
    });

    it('opens the popover with the full cell value on click', () => {
        bodyCells()[1].click();
        fixture.detectChanges();

        expect(popover()?.textContent?.trim()).toBe('A long description of the first entity');
    });

    it('opens the popover on Enter and on Space and prevents the default key action', () => {
        const enter = pressKey(bodyCells()[0], 'Enter');
        expect(popover()?.textContent?.trim()).toBe('Entity 1');
        expect(enter.defaultPrevented).toBe(true);

        const space = pressKey(bodyCells()[2], ' ');
        expect(popover()?.textContent?.trim()).toBe('Entity 2');
        expect(space.defaultPrevented).toBe(true);
    });

    it('shows an empty popover for a null value', () => {
        bodyCells()[3].click();
        fixture.detectChanges();

        expect(popover()).not.toBeNull();
        expect(popover()?.textContent?.trim()).toBe('');
    });

    it('closes the popover on Escape and returns focus to the cell it was opened from', () => {
        const cell = bodyCells()[1];
        cell.focus();
        pressKey(cell, 'Enter');
        expect(popover()).not.toBeNull();

        pressKey(document, 'Escape');

        expect(popover()).toBeNull();
        expect(document.activeElement).toBe(cell);
    });

    it('closes the popover on a pointer down outside it but not inside it', () => {
        bodyCells()[0].click();
        fixture.detectChanges();

        popover()!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        fixture.detectChanges();
        expect(popover()).not.toBeNull();

        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        fixture.detectChanges();
        expect(popover()).toBeNull();
    });

    it('emits the action name and row when an action cell is clicked or activated, and keeps the popover closed', () => {
        fixture.componentInstance.columnDefs.set(COLUMN_DEFS_WITH_ACTION);
        fixture.detectChanges();

        // Three columns per row: [0] title, [1] description, [2] action; [3..5] second row.
        const actionCellRow1 = bodyCells()[2];
        const actionCellRow2 = bodyCells()[5];
        actionCellRow1.click();
        pressKey(actionCellRow2, 'Enter');

        expect(fixture.componentInstance.actions).toEqual([
            { action: 'view', row: ROWS[0] },
            { action: 'view', row: ROWS[1] },
        ]);
        expect(popover()).toBeNull();
    });

    it('leaves the action column header blank and omits its resize handle', () => {
        fixture.componentInstance.columnDefs.set(COLUMN_DEFS_WITH_ACTION);
        fixture.detectChanges();

        const headers = Array.from(host.querySelectorAll<HTMLElement>('[role="columnheader"]'));
        expect(headers[2].querySelector('.grid-table-col-label')?.textContent?.trim()).toBe('');
        expect(headers[2].querySelector('.grid-table-resize-handle')).toBeNull();
    });

    it('highlights the search term inside the cells', () => {
        fixture.componentInstance.searchTerm.set('entity');
        fixture.detectChanges();

        const marks = Array.from(host.querySelectorAll('[role="gridcell"] mark.grid-table-highlight')).map(
            (mark) => mark.textContent
        );
        expect(marks).toEqual(['Entity', 'entity', 'Entity']);
    });
});
