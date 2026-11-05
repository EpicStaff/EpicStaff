import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { KeyValueListComponent } from './key-value-list.component';

// jsdom has no ResizeObserver; the overflow tooltips only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

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

    function describedBy(element: HTMLElement): string[] {
        return (element.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
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
        // The name tooltip may add its own description id: only which input the error describes matters here.
        expect(describedBy(valueInput)).toContain(error.id);
        expect(describedBy(field(fixture, 0, 'name'))).not.toContain(error.id);
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

@Component({
    imports: [KeyValueListComponent, ReactiveFormsModule],
    template: `<app-key-value-list
        [formControl]="control"
        rowLabel="Option"
        [secretSuggestions]="false"
        [headerRules]="false"
    />`,
})
class PlainHostComponent {
    readonly control = new FormControl<Record<string, string>>({});
}

describe('KeyValueListComponent as a plain name-to-text list', () => {
    let getSecrets: ReturnType<typeof vi.fn>;

    function setup() {
        getSecrets = vi.fn(() => of([]));
        TestBed.configureTestingModule({
            providers: [{ provide: SecretsStorageService, useValue: { secrets: () => [], getSecrets } }],
        });
        const fixture = TestBed.createComponent(PlainHostComponent);
        fixture.detectChanges();
        return { fixture, control: fixture.componentInstance.control };
    }

    function inputs(fixture: ComponentFixture<PlainHostComponent>): HTMLInputElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('input'));
    }

    function type(fixture: ComponentFixture<PlainHostComponent>, input: HTMLInputElement, text: string): void {
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    it('names rows after the row label for assistive tech', () => {
        const { fixture } = setup();

        const [name, value] = inputs(fixture);

        expect(name.getAttribute('aria-label')).toBe('Option name, row 1');
        expect(value.getAttribute('aria-label')).toBe('Option value, row 1');
        expect(fixture.nativeElement.querySelector('.kv-list__remove-btn').getAttribute('aria-label')).toBe(
            'Remove option, row 1'
        );
    });

    it('accepts a name with spaces and emits it, with no header error', () => {
        const { fixture, control } = setup();

        type(fixture, inputs(fixture)[0], 'Very senior');
        type(fixture, inputs(fixture)[1], 'Ten years or more');

        expect(fixture.nativeElement.querySelector('.kv-list__error-message')).toBeNull();
        expect(control.value).toEqual({ 'Very senior': 'Ten years or more' });
        expect(control.valid).toBe(true);
    });

    it('treats names that differ only in case as different, and flags an exact duplicate', () => {
        const { fixture, control } = setup();
        control.setValue({ Eng: 'a', eng: 'b' });
        fixture.detectChanges();
        expect(control.valid).toBe(true);

        control.setValue({ Eng: 'a' });
        fixture.detectChanges();
        type(fixture, inputs(fixture)[2], 'Eng');
        type(fixture, inputs(fixture)[3], 'b');

        expect(fixture.nativeElement.querySelector('.kv-list__error-message').textContent.trim()).toBe(
            'Duplicate name'
        );
    });

    it('uses plain copy for a missing value', () => {
        const { fixture } = setup();

        type(fixture, inputs(fixture)[0], 'eng');

        expect(fixture.nativeElement.querySelector('.kv-list__error-message').textContent.trim()).toBe(
            'Value is required'
        );
    });

    it('does not fetch secrets or offer them on the value field', () => {
        const { fixture } = setup();

        inputs(fixture)[1].dispatchEvent(new Event('focus'));
        fixture.detectChanges();

        expect(getSecrets).not.toHaveBeenCalled();
        expect(document.querySelector('.kv-list__suggestions')).toBeNull();
    });

    it('shows a value that looks like a secret marker as the plain text it is', async () => {
        const { fixture, control } = setup();
        control.setValue({ eng: 'epicstaff_secret(key)' });
        fixture.detectChanges();
        await fixture.whenStable();

        expect(inputs(fixture)[1].value).toBe('epicstaff_secret(key)');
        expect(fixture.nativeElement.querySelector('.kv-list__secret-badge')).toBeNull();
    });
});

@Component({
    imports: [KeyValueListComponent, ReactiveFormsModule],
    template: `<app-key-value-list
        [formControl]="control"
        [compact]="true"
    />`,
})
class CompactHostComponent {
    readonly control = new FormControl<Record<string, string>>({});
}

describe('KeyValueListComponent compact', () => {
    function render<T>(host: new () => T): HTMLElement {
        TestBed.configureTestingModule({
            providers: [{ provide: SecretsStorageService, useValue: { secrets: () => [], getSecrets: () => of([]) } }],
        });
        const fixture = TestBed.createComponent(host);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it('is framed by default and drops the frame only when asked', () => {
        expect(render(HostComponent).querySelector('.kv-list--compact')).toBeNull();
    });

    it('marks the list compact when the input is set', () => {
        expect(render(CompactHostComponent).querySelector('.kv-list--compact')).not.toBeNull();
    });
});

describe('KeyValueListComponent defaults', () => {
    it('keeps header rules and the secrets picker for callers that set nothing', () => {
        const getSecrets = vi.fn(() => of([]));
        TestBed.configureTestingModule({
            providers: [{ provide: SecretsStorageService, useValue: { secrets: () => [], getSecrets } }],
        });
        const fixture = TestBed.createComponent(HostComponent);
        fixture.componentInstance.control.setValue({ 'X Team': 'v' });
        fixture.detectChanges();

        expect(getSecrets).toHaveBeenCalledTimes(1);
        expect(fixture.nativeElement.querySelector('.kv-list__error-message').textContent.trim()).toBe(
            "Header names can't contain spaces or special characters"
        );
    });
});
