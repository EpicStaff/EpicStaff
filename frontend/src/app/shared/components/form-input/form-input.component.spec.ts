import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { CustomInputComponent } from './form-input.component';

@Component({
    imports: [ReactiveFormsModule, CustomInputComponent],
    template: `<app-custom-input [formControl]="control" />`,
})
class HostComponent {
    readonly control = new FormControl('');
}

@Component({
    selector: 'app-initially-disabled-control-host',
    imports: [ReactiveFormsModule, CustomInputComponent],
    template: `<app-custom-input [formControl]="control" />`,
})
class InitiallyDisabledControlHostComponent {
    readonly control = new FormControl({ value: 'user@example.com', disabled: true });
}

@Component({
    selector: 'app-disabled-input-host',
    imports: [CustomInputComponent],
    template: `<app-custom-input [disabled]="true" />`,
})
class DisabledInputHostComponent {}

describe('CustomInputComponent', () => {
    let fixture: ComponentFixture<HostComponent>;

    const input = (): HTMLInputElement => fixture.nativeElement.querySelector('input');

    beforeEach(() => {
        fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();
    });

    it('disables and re-enables the input in the same change detection as its control', () => {
        fixture.componentInstance.control.disable();
        fixture.detectChanges();
        expect(input().disabled).toBe(true);

        fixture.componentInstance.control.enable();
        fixture.detectChanges();
        expect(input().disabled).toBe(false);
    });

    it('passes typed text to its control and shows values set on the control', () => {
        input().value = 'typed';
        input().dispatchEvent(new Event('input'));
        expect(fixture.componentInstance.control.value).toBe('typed');

        fixture.componentInstance.control.setValue('from control');
        fixture.detectChanges();
        expect(input().value).toBe('from control');
    });

    it('passes composed text to its control only once the composition ends', () => {
        input().dispatchEvent(new CompositionEvent('compositionstart'));
        input().value = 'ni';
        input().dispatchEvent(new Event('input'));
        expect(fixture.componentInstance.control.value).toBe('');

        input().value = '你';
        input().dispatchEvent(new CompositionEvent('compositionend'));
        expect(fixture.componentInstance.control.value).toBe('你');
    });

    it.each([
        ['its control is created disabled', InitiallyDisabledControlHostComponent],
        ['its disabled input is set', DisabledInputHostComponent],
    ])('renders the input disabled from the start when %s', (_case, host) => {
        const disabledFixture = TestBed.createComponent<object>(host);
        disabledFixture.detectChanges();

        const disabledInput: HTMLInputElement = disabledFixture.nativeElement.querySelector('input');
        expect(disabledInput.disabled).toBe(true);
    });
});
