import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { StringListComponent } from './string-list.component';

@Component({
    imports: [StringListComponent, ReactiveFormsModule],
    template: `<app-string-list
        [formControl]="control"
        [label]="label"
        addButtonText="+ Add origin"
        rowLabel="Origin"
    />`,
})
class HostComponent {
    readonly control = new FormControl<string[]>([], { nonNullable: true });
    label = '';
}

describe('StringListComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let control: FormControl<string[]>;

    function setup(value: string[] | null, label = ''): void {
        fixture = TestBed.createComponent(HostComponent);
        fixture.componentInstance.label = label;
        control = fixture.componentInstance.control;
        control.setValue(value as string[]);
        fixture.detectChanges();
    }

    function rows(): HTMLInputElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('input'));
    }

    function values(): string[] {
        return rows().map((row) => row.value);
    }

    function type(row: number, text: string): void {
        const input = rows()[row];
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function removeButton(row: number): HTMLButtonElement {
        const button = fixture.nativeElement.querySelector(`[aria-label="Remove origin, row ${row + 1}"]`);
        if (!button) throw new Error(`No remove button on row ${row + 1}`);
        return button;
    }

    function addButton(): HTMLButtonElement | undefined {
        return Array.from<HTMLButtonElement>(fixture.nativeElement.querySelectorAll('button')).find(
            (button) => button.textContent?.trim() === '+ Add origin'
        );
    }

    function clickAdd(): void {
        addButton()?.click();
        fixture.detectChanges();
    }

    it.each([
        ['an empty list', [], ['']],
        ['null', null, ['']],
        ['saved values', ['https://a.example', 'https://b.example'], ['https://a.example', 'https://b.example']],
    ])('shows one row per value, or one empty row, for %s', (_, value, shown) => {
        setup(value);
        expect(values()).toEqual(shown);
    });

    it('labels each row and its remove button by position for screen readers', () => {
        setup(['https://a.example', 'https://b.example']);
        expect(rows().map((row) => row.getAttribute('aria-label'))).toEqual(['Origin, row 1', 'Origin, row 2']);
        expect(removeButton(1)).toBeTruthy();
    });

    it('appends an empty row and puts the cursor in it', async () => {
        setup(['https://a.example']);
        clickAdd();
        // The cursor moves once the new row is drawn.
        await fixture.whenStable();
        expect(values()).toEqual(['https://a.example', '']);
        expect(document.activeElement).toBe(rows()[1]);
    });

    it('removes any row, the first, the last and the only one included', () => {
        setup(['https://a.example', 'https://b.example', 'https://c.example']);
        removeButton(0).click();
        fixture.detectChanges();
        expect(values()).toEqual(['https://b.example', 'https://c.example']);
        expect(control.value).toEqual(['https://b.example', 'https://c.example']);

        removeButton(1).click();
        fixture.detectChanges();
        removeButton(0).click();
        fixture.detectChanges();
        expect(rows()).toEqual([]);
        expect(control.value).toEqual([]);
    });

    it.each([
        ['the row that moved into its place', ['a', 'b', 'c'], 1, () => rows()[1]],
        ['the row above, when the last row is removed', ['a', 'b', 'c'], 2, () => rows()[1]],
        ['the add button, when no row is left', ['a'], 0, () => addButton()],
    ])('after a remove, puts the cursor in %s', async (_, value, removedRow, focused) => {
        setup(value);
        removeButton(removedRow).click();
        fixture.detectChanges();
        // The cursor moves once the list is redrawn.
        await fixture.whenStable();
        expect(document.activeElement).toBe(focused());
    });

    it.each([
        ['names the rows group after the label', 'Allowed origins', 'Allowed origins'],
        ['leaves the rows group unnamed without a label', '', null],
    ])('%s', (_, label, groupName) => {
        setup(['https://a.example'], label);
        const group: HTMLElement = fixture.nativeElement.querySelector('[role="group"]');
        expect(group.contains(rows()[0])).toBe(true);
        expect(group.getAttribute('aria-label')).toBe(groupName);
    });

    it('keeps the add button with no rows and with many', () => {
        setup([]);
        removeButton(0).click();
        fixture.detectChanges();
        expect(addButton()).toBeTruthy();

        clickAdd();
        clickAdd();
        clickAdd();
        expect(rows().length).toBe(3);
        expect(addButton()).toBeTruthy();
    });

    it('sends the typed values trimmed, without the empty or blank rows', () => {
        setup([]);
        type(0, '  https://a.example ');
        clickAdd();
        clickAdd();
        type(2, '   ');
        clickAdd();
        type(3, 'https://b.example');
        expect(control.value).toEqual(['https://a.example', 'https://b.example']);
        // The rows keep what was typed until the form writes a value back.
        expect(values()).toEqual(['  https://a.example ', '', '   ', 'https://b.example']);
    });

    it('marks the control touched when a row loses focus', () => {
        setup([]);
        expect(control.touched).toBe(false);
        rows()[0].dispatchEvent(new Event('blur'));
        expect(control.touched).toBe(true);
    });

    it('disables the rows, the remove buttons and the add button with the control, and enables them again', () => {
        setup(['https://a.example']);
        control.disable();
        fixture.detectChanges();
        expect(rows()[0].disabled).toBe(true);
        expect(removeButton(0).disabled).toBe(true);
        expect(addButton()?.disabled).toBe(true);

        control.enable();
        fixture.detectChanges();
        expect(rows()[0].disabled).toBe(false);
        expect(addButton()?.disabled).toBe(false);
    });
});
