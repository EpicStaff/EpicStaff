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
});
