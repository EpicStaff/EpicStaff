import { TestBed } from '@angular/core/testing';

import { NumberStepperComponent } from './number-stepper.component';

function blurEmptyField(allowEmpty: boolean): number | null {
    const fixture = TestBed.createComponent(NumberStepperComponent);
    fixture.componentRef.setInput('integer', true);
    fixture.componentRef.setInput('min', 5);
    fixture.componentRef.setInput('allowEmpty', allowEmpty);
    fixture.componentRef.setInput('value', null);
    fixture.detectChanges();

    (fixture.nativeElement as HTMLElement).querySelector('input')!.dispatchEvent(new Event('blur'));
    return fixture.componentInstance.value();
}

describe('NumberStepperComponent blur in integer mode', () => {
    it('keeps a cleared field empty when allowEmpty is set', () => {
        expect(blurEmptyField(true)).toBeNull();
    });

    it('fills a cleared field with min by default', () => {
        expect(blurEmptyField(false)).toBe(5);
    });
});
