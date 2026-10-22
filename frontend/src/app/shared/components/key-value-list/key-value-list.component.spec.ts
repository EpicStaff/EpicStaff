import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { KeyValueListComponent } from './key-value-list.component';

@Component({
    imports: [KeyValueListComponent, ReactiveFormsModule],
    template: `<app-key-value-list [formControl]="control" />`,
})
class HostComponent {
    readonly control = new FormControl<Record<string, string>>({});
}

describe('KeyValueListComponent', () => {
    function setup() {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: () => [], getSecrets: () => of([]) },
                },
            ],
        });
        const fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
        const list = fixture.debugElement.children[0].componentInstance as KeyValueListComponent;
        return { fixture, control: fixture.componentInstance.control, list };
    }

    function inputs(fixture: ComponentFixture<HostComponent>): HTMLInputElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('input'));
    }

    function type(fixture: ComponentFixture<HostComponent>, input: HTMLInputElement, text: string): void {
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function field(fixture: ComponentFixture<HostComponent>, row: number, kind: 'name' | 'value'): HTMLInputElement {
        return inputs(fixture)[row * 2 + (kind === 'name' ? 0 : 1)];
    }

    function removeButtons(fixture: ComponentFixture<HostComponent>): HTMLButtonElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('.kv-list__remove-btn'));
    }

    function errorTexts(fixture: ComponentFixture<HostComponent>): string[] {
        return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.kv-list__error-message')).map((el) =>
            el.textContent!.trim()
        );
    }

    it('is invalid when a saved row has a bad header name and valid once the user fixes it', () => {
        const { fixture, control } = setup();
        control.setValue({ 'bad name': 'x' });
        fixture.detectChanges();
        expect(control.invalid).toBe(true);

        type(fixture, field(fixture, 0, 'name'), 'good-name');
        expect(control.valid).toBe(true);
        expect(control.value).toEqual({ 'good-name': 'x' });
    });

    it('stays valid-correct after reset or patchValue without events', () => {
        const { fixture, control } = setup();
        control.setValue({ 'bad name': 'x' }, { emitEvent: false });
        fixture.detectChanges();
        expect(control.invalid).toBe(true);

        control.reset({}, { emitEvent: false });
        fixture.detectChanges();
        expect(control.valid).toBe(true);
    });

    it('does not emit or mark the control dirty when the value is written programmatically', async () => {
        const { fixture, control } = setup();
        const emitted: unknown[] = [];
        control.valueChanges.subscribe((value) => emitted.push(value));
        control.setValue({ 'X-Name': 'a' }, { emitEvent: false });
        fixture.detectChanges();
        await fixture.whenStable();

        expect(emitted).toEqual([]);
        expect(control.dirty).toBe(false);
        expect(control.touched).toBe(false);
        expect(field(fixture, 0, 'name').value).toBe('X-Name');
    });

    it('emits trimmed names', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), '  X-Name  ');
        type(fixture, field(fixture, 0, 'value'), 'abc');

        expect(control.value).toEqual({ 'X-Name': 'abc' });
    });

    it('hides the remove button on the spare row only', () => {
        const { fixture, control } = setup();
        control.setValue({ 'X-Name': 'a' });
        fixture.detectChanges();

        const hidden = removeButtons(fixture).map((button) => button.classList.contains('kv-list__remove-btn--hidden'));
        expect(hidden).toEqual([false, true]);
    });

    it('leaves exactly one empty row after the last real row is cleared', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), 'X-Name');
        type(fixture, field(fixture, 0, 'value'), 'abc');
        type(fixture, field(fixture, 0, 'name'), '');
        type(fixture, field(fixture, 0, 'value'), '');

        expect(inputs(fixture).length).toBe(2);
        expect(control.value).toEqual({});
        expect(control.valid).toBe(true);
    });

    it('labels inputs and links an error to its input for assistive tech', () => {
        const { fixture } = setup();
        type(fixture, field(fixture, 0, 'name'), 'X-Name');

        const valueInput = field(fixture, 0, 'value');
        const error = fixture.nativeElement.querySelector('.kv-list__error-message') as HTMLElement;
        expect(field(fixture, 0, 'name').getAttribute('aria-label')).toBe('Header name, row 1');
        expect(valueInput.getAttribute('aria-label')).toBe('Header value, row 1');
        expect(valueInput.getAttribute('aria-invalid')).toBe('true');
        expect(valueInput.getAttribute('aria-describedby')).toBe(error.id);
        expect(field(fixture, 0, 'name').getAttribute('aria-describedby')).toBeNull();
        expect(removeButtons(fixture)[0].getAttribute('aria-label')).toBe('Remove header, row 1');
    });

    it('emits a typed row immediately, without any confirmation, and offers a new empty row', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), 'X-Name');
        type(fixture, field(fixture, 0, 'value'), 'abc');

        expect(control.value).toEqual({ 'X-Name': 'abc' });
        expect(control.valid).toBe(true);
        expect(inputs(fixture).length).toBe(4);
    });

    it('ignores a row where both name and value are empty', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), '   ');

        expect(control.valid).toBe(true);
        expect(control.value).toEqual({});
        expect(errorTexts(fixture)).toEqual([]);
    });

    it('requires a value when only the name is filled', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), 'X-Name');

        expect(control.invalid).toBe(true);
        expect(control.value).toEqual({});
        expect(errorTexts(fixture)).toEqual(['Header value is required']);

        type(fixture, field(fixture, 0, 'value'), 'abc');
        expect(control.valid).toBe(true);
        expect(errorTexts(fixture)).toEqual([]);
    });

    it('requires a name when only the value is filled', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'value'), 'abc');

        expect(control.invalid).toBe(true);
        expect(control.value).toEqual({});
        expect(errorTexts(fixture)).toEqual(['Header name is required']);
    });

    it('rejects a duplicate name case-insensitively', () => {
        const { fixture, control } = setup();
        control.setValue({ 'X-Name': 'a' });
        fixture.detectChanges();
        type(fixture, field(fixture, 1, 'name'), 'x-name');
        type(fixture, field(fixture, 1, 'value'), 'b');

        expect(control.invalid).toBe(true);
        expect(errorTexts(fixture)).toContain('Duplicate header name');
    });

    it('rejects a name with spaces', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), 'bad name');
        type(fixture, field(fixture, 0, 'value'), 'v');

        expect(control.invalid).toBe(true);
        expect(errorTexts(fixture)).toEqual(["Header names can't contain spaces or special characters"]);
    });

    it('stops blocking once a half-filled row is removed', () => {
        const { fixture, control } = setup();
        type(fixture, field(fixture, 0, 'name'), 'X-Name');
        expect(control.invalid).toBe(true);

        removeButtons(fixture)[0].click();
        fixture.detectChanges();

        expect(control.valid).toBe(true);
    });

    it('ignores an entirely empty row', () => {
        const { fixture, control } = setup();
        control.setValue({ '': '' });
        fixture.detectChanges();
        expect(control.valid).toBe(true);
    });
});
