import { DialogRef } from '@angular/cdk/dialog';
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { EnterSubmitDirective } from '@shared/directives';
import { Subject } from 'rxjs';

import { StringListComponent } from './string-list.component';

const NOT_HTTPS = 'Use an https address';

@Component({
    imports: [StringListComponent, ReactiveFormsModule, EnterSubmitDirective],
    template: `<div (appEnterSubmit)="submits = submits + 1">
        <app-string-list
            [formControl]="control"
            [label]="label"
            addButtonText="+ Add origin"
            rowLabel="Origin"
            [splitPattern]="splitPattern"
            [itemError]="itemError"
            [maxItems]="maxItems"
            [maxItemsText]="maxItemsText"
        />
    </div>`,
})
class HostComponent {
    readonly control = new FormControl<string[]>([], { nonNullable: true });
    label = '';
    splitPattern: RegExp | null = null;
    itemError: ((value: string) => string | null) | null = null;
    maxItems: number | null = null;
    maxItemsText = '';
    submits = 0;
}

interface Options {
    label?: string;
    split?: boolean;
    httpsOnly?: boolean;
    maxItems?: number;
}

describe('StringListComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let control: FormControl<string[]>;
    // The dialog hands keys to its content after they have passed the focused element, as the CDK overlay does.
    const dialogKeys = new Subject<KeyboardEvent>();

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [{ provide: DialogRef, useValue: { keydownEvents: dialogKeys } }],
        });
    });

    function setup(value: string[] | null, options: Options = {}): void {
        fixture = TestBed.createComponent(HostComponent);
        const host = fixture.componentInstance;
        host.label = options.label ?? '';
        host.splitPattern = options.split ? /[\s,]+/ : null;
        host.itemError = options.httpsOnly ? (text) => (text.startsWith('https://') ? null : NOT_HTTPS) : null;
        host.maxItems = options.maxItems ?? null;
        host.maxItemsText = options.maxItems ? `Up to ${options.maxItems} origins` : '';
        control = host.control;
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

    /** Puts the cursor in the row, the text from `start` to `end` selected. */
    function select(row: number, start: number, end = start): HTMLInputElement {
        const input = rows()[row];
        input.focus();
        input.setSelectionRange(start, end);
        return input;
    }

    /** Pastes over the selection, as the browser does unless the list takes the paste. */
    async function paste(row: number, text: string, start: number, end = start): Promise<void> {
        const input = select(row, start, end);
        const event = new Event('paste', { bubbles: true, cancelable: true });
        Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } });
        input.dispatchEvent(event);
        if (!event.defaultPrevented) {
            input.value = input.value.slice(0, start) + text + input.value.slice(end);
            input.dispatchEvent(new Event('input'));
        }
        fixture.detectChanges();
        // The cursor moves once the rows are drawn.
        await fixture.whenStable();
    }

    /** Types one character at the cursor, as the browser does unless the list takes it. */
    async function typeCharacter(row: number, character: string, caret: number): Promise<void> {
        const input = select(row, caret);
        const event = new InputEvent('beforeinput', {
            bubbles: true,
            cancelable: true,
            data: character,
            inputType: 'insertText',
        });
        input.dispatchEvent(event);
        if (!event.defaultPrevented) {
            input.value = input.value.slice(0, caret) + character + input.value.slice(caret);
            input.dispatchEvent(new Event('input'));
        }
        fixture.detectChanges();
        await fixture.whenStable();
    }

    async function pressEnter(row: number): Promise<void> {
        const input = rows()[row];
        input.focus();
        const event = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true });
        input.dispatchEvent(event);
        dialogKeys.next(event);
        fixture.detectChanges();
        await fixture.whenStable();
    }

    /** Leaves the row, as tabbing out of it does (a row never focused cannot lose focus). */
    function blur(row: number): void {
        const input = rows()[row];
        input.focus();
        input.blur();
        fixture.detectChanges();
    }

    /** The error each row's input points at, null for a row without one. */
    function rowErrors(): (string | null)[] {
        return rows().map((row) => {
            const id = row.getAttribute('aria-describedby');
            return id ? (document.getElementById(id)?.textContent?.trim() ?? null) : null;
        });
    }

    function errorTexts(): string[] {
        return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.string-list__error')).map(
            (error) => error.textContent?.trim() ?? ''
        );
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
        setup(['https://a.example'], { label });
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

    describe('splitting at separators', () => {
        it.each([
            {
                name: 'into the empty row, one piece per row',
                value: [''],
                pasted: 'https://a.example, https://b.example\nhttps://c.example',
                at: [0, 0, 0],
                shown: ['https://a.example', 'https://b.example', 'https://c.example'],
                lastRow: 2,
            },
            {
                name: 'at the cursor in the middle of a row, the text after the cursor ending the last piece',
                value: ['https://a.examplehttps://d.example'],
                pasted: 'X https://b.example ',
                at: [0, 17, 17],
                shown: ['https://a.exampleX', 'https://b.example', 'https://d.example'],
                lastRow: 2,
            },
            {
                name: 'over the selection',
                value: ['https://old.example', 'https://z.example'],
                pasted: 'https://a.example,https://b.example',
                at: [0, 0, 19],
                shown: ['https://a.example', 'https://b.example', 'https://z.example'],
                lastRow: 1,
            },
            {
                name: 'without the blank pieces',
                value: [''],
                pasted: ' ,, https://a.example ,\n\n, https://b.example,, ',
                at: [0, 0, 0],
                shown: ['https://a.example', 'https://b.example'],
                lastRow: 1,
            },
            {
                name: 'without the pieces an earlier piece holds, keeping the ones another row holds',
                value: ['https://a.example', ''],
                pasted: 'https://a.example https://b.example https://b.example https://c.example',
                at: [1, 0, 0],
                shown: ['https://a.example', 'https://a.example', 'https://b.example', 'https://c.example'],
                lastRow: 3,
            },
        ])('pastes $name, the cursor at the end of the last piece', async ({ value, pasted, at, shown, lastRow }) => {
            setup(value, { split: true });
            const [row, start, end] = at;
            await paste(row, pasted, start, end);
            expect(values()).toEqual(shown);
            expect(control.value).toEqual(shown);
            const last = rows()[lastRow];
            expect(document.activeElement).toBe(last);
            expect(last.selectionStart).toBe(last.value.length);
        });

        it('pastes text without a separator as the browser does', async () => {
            setup(['https://a.example'], { split: true });
            await paste(0, '/x', 17);
            expect(values()).toEqual(['https://a.example/x']);
        });

        it('keeps pasted separators in the row without a split pattern', async () => {
            setup([''], {});
            await paste(0, 'https://a.example, https://b.example', 0);
            expect(values()).toEqual(['https://a.example, https://b.example']);
        });

        it('ends the row at a typed separator, the text after it going to a new row with the cursor', async () => {
            setup(['https://a.examplehttps://b.example', 'https://c.example'], { split: true });
            await typeCharacter(0, ',', 17);
            expect(values()).toEqual(['https://a.example', 'https://b.example', 'https://c.example']);
            expect(document.activeElement).toBe(rows()[1]);
            expect(rows()[1].selectionStart).toBe(0);
        });

        it('moves to a new empty row at a separator typed at the end, so the next value goes there', async () => {
            setup(['https://a.example'], { split: true });
            await typeCharacter(0, ' ', 17);
            expect(values()).toEqual(['https://a.example', '']);
            expect(document.activeElement).toBe(rows()[1]);
        });

        it('keeps a row that repeats another one at a typed separator, adding the one new row', async () => {
            setup(['https://a.example', ''], { split: true });
            type(1, 'https://a.example');
            await typeCharacter(1, ' ', 17);
            expect(values()).toEqual(['https://a.example', 'https://a.example', '']);
            expect(control.value).toEqual(['https://a.example', 'https://a.example']);
            expect(document.activeElement).toBe(rows()[2]);
        });

        it('adds no row at a separator typed between a value and its repeat', async () => {
            setup(['https://a.examplehttps://a.example'], { split: true });
            await typeCharacter(0, ',', 17);
            expect(values()).toEqual(['https://a.example']);
        });

        it.each([
            ['an empty row', [''], 0, ['']],
            ['the start of a row', ['https://a.example'], 0, ['https://a.example']],
            ['a row of blanks', ['   '], 3, ['   ']],
        ])('drops a separator typed into %s, adding no row', async (_, value, caret, shown) => {
            setup(value, { split: true });
            await typeCharacter(0, ',', caret);
            expect(values()).toEqual(shown);
        });

        it('splits on leaving a row what is still separated, without blanks or repeats within it', () => {
            setup(['https://a.example', ''], { split: true });
            // As autofill does: no paste, no typed key.
            type(1, 'https://b.example, https://a.example  https://b.example');
            blur(1);
            expect(values()).toEqual(['https://a.example', 'https://b.example', 'https://a.example']);
            expect(control.value).toEqual(['https://a.example', 'https://b.example', 'https://a.example']);
        });

        it('keeps a written value with a separator in one row when the row is left unedited', () => {
            setup(['https://a.example, https://b.example'], { split: true });
            blur(0);
            expect(values()).toEqual(['https://a.example, https://b.example']);
            expect(control.value).toEqual(['https://a.example, https://b.example']);
        });

        it('splits a written value with a separator once the row is edited and left', () => {
            setup(['https://a.example, https://b.example'], { split: true });
            type(0, 'https://a.example, https://b.example/');
            blur(0);
            expect(values()).toEqual(['https://a.example', 'https://b.example/']);
        });
    });

    describe('Enter', () => {
        it('adds an empty row right after this one and moves there, without submitting', async () => {
            setup(['https://a.example', 'https://b.example']);
            await pressEnter(0);
            expect(values()).toEqual(['https://a.example', '', 'https://b.example']);
            expect(document.activeElement).toBe(rows()[1]);
            expect(fixture.componentInstance.submits).toBe(0);
        });

        it('in an empty row moves to the next row instead of adding one', async () => {
            setup(['https://a.example', 'https://b.example']);
            await pressEnter(0);
            await pressEnter(1);
            expect(values()).toEqual(['https://a.example', '', 'https://b.example']);
            expect(document.activeElement).toBe(rows()[2]);
        });

        it('at the cap adds no row and moves to the next one', async () => {
            setup(['https://a.example', 'https://b.example'], { maxItems: 2 });
            await pressEnter(0);
            expect(values()).toEqual(['https://a.example', 'https://b.example']);
            expect(document.activeElement).toBe(rows()[1]);
        });

        it('while an input method is composing adds no row and leaves the key to it', async () => {
            setup(['https://a.example']);
            const input = rows()[0];
            input.focus();
            const event = new KeyboardEvent('keydown', {
                key: 'Enter',
                code: 'Enter',
                bubbles: true,
                cancelable: true,
                isComposing: true,
            });
            // Only the list sees the key: the dialog's own Enter handling is not what this checks.
            input.dispatchEvent(event);
            fixture.detectChanges();
            await fixture.whenStable();
            expect(values()).toEqual(['https://a.example']);
            expect(event.defaultPrevented).toBe(false);
        });

        it('in an empty last row does nothing, and still does not submit', async () => {
            setup([]);
            await pressEnter(0);
            expect(values()).toEqual(['']);
            expect(document.activeElement).toBe(rows()[0]);
            expect(fixture.componentInstance.submits).toBe(0);
        });
    });

    describe('row errors', () => {
        it('shows the error of a typed row once the row is left, linked to it for screen readers', () => {
            setup([], { httpsOnly: true });
            rows()[0].focus();
            type(0, 'http://a.example');
            expect(control.invalid).toBe(true);
            expect(errorTexts()).toEqual([]);
            expect(rows()[0].getAttribute('aria-invalid')).toBeNull();

            blur(0);
            expect(rowErrors()).toEqual([NOT_HTTPS]);
            expect(rows()[0].getAttribute('aria-invalid')).toBe('true');
            expect(rows()[0].classList).toContain('string-list__input--error');
        });

        it('shows the errors of saved rows once the control is touched, as a save attempt does', () => {
            setup(['http://a.example', 'https://b.example'], { httpsOnly: true });
            expect(control.invalid).toBe(true);
            expect(errorTexts()).toEqual([]);

            control.markAllAsTouched();
            fixture.detectChanges();
            expect(rowErrors()).toEqual([NOT_HTTPS, null]);
        });

        it('hides the error of a row typed for the first time, even with the control touched', async () => {
            setup(['http://a.example'], { httpsOnly: true });
            control.markAllAsTouched();
            await pressEnter(0);
            type(1, 'http://b.example');
            expect(rowErrors()).toEqual([NOT_HTTPS, null]);

            blur(1);
            expect(rowErrors()).toEqual([NOT_HTTPS, NOT_HTTPS]);
        });

        it('makes the control valid again once the row is fixed, and never faults an empty row', () => {
            setup(['http://a.example', ''], { httpsOnly: true });
            control.markAllAsTouched();
            type(0, 'https://a.example');
            blur(1);
            expect(control.valid).toBe(true);
            expect(errorTexts()).toEqual([]);
        });
    });

    describe('the cap', () => {
        function addTooltip(): MatTooltip {
            return fixture.debugElement.query(By.css('.string-list__add-host')).injector.get(MatTooltip);
        }

        it('disables the add button at the cap, saying why, counting only the filled rows', () => {
            setup(['https://a.example', ''], { maxItems: 2 });
            expect(addButton()?.disabled).toBe(false);
            expect(addTooltip().disabled).toBe(true);

            type(1, 'https://b.example');
            expect(addButton()?.disabled).toBe(true);
            expect(addTooltip().disabled).toBe(false);
            expect(addTooltip().message).toBe('Up to 2 origins');
            expect(control.valid).toBe(true);
            expect(errorTexts()).toEqual([]);
        });

        it('keeps the rows a paste puts over the cap, invalid with the cap said under the list', async () => {
            setup(['https://a.example', ''], { split: true, maxItems: 2 });
            await paste(1, 'https://b.example https://c.example', 0);
            expect(values()).toEqual(['https://a.example', 'https://b.example', 'https://c.example']);
            expect(control.errors).toEqual({ stringListMaxItems: { max: 2, actual: 3 } });
            expect(errorTexts()).toEqual(['Up to 2 origins']);
            const group: HTMLElement = fixture.nativeElement.querySelector('[role="group"]');
            const describedBy = group.getAttribute('aria-describedby') ?? '';
            expect(document.getElementById(describedBy)?.textContent?.trim()).toBe('Up to 2 origins');

            removeButton(2).click();
            fixture.detectChanges();
            expect(control.valid).toBe(true);
            expect(errorTexts()).toEqual([]);
        });
    });
});
