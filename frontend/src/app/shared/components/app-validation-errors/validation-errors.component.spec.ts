import { TestBed } from '@angular/core/testing';
import { FormControl, ValidationErrors } from '@angular/forms';

import { ValidationErrorsComponent } from './validation-errors.component';

describe('ValidationErrorsComponent', () => {
    function shownFor(errors: ValidationErrors, touched = true): string[] {
        const control = new FormControl('');
        control.setErrors(errors);
        if (touched) control.markAsTouched();
        const fixture = TestBed.createComponent(ValidationErrorsComponent);
        fixture.componentRef.setInput('control', control);
        fixture.detectChanges();
        const host: HTMLElement = fixture.nativeElement;
        return Array.from(host.querySelectorAll('.validation-errors__item')).map(
            (item) => item.textContent?.trim() ?? ''
        );
    }

    it.each([
        { errors: { required: true }, shown: ['This field is required.'] },
        // A validator's own wording, for a key the component does not know.
        { errors: { aboveCap: 'At most 5 on this deployment.' }, shown: ['At most 5 on this deployment.'] },
        // A known key keeps its own wording whatever its value holds.
        { errors: { min: { min: 1, actual: 0 } }, shown: ['Min value is 1.'] },
        { errors: { custom: true }, shown: ['custom is invalid.'] },
        { errors: { custom: '  ' }, shown: ['custom is invalid.'] },
        { errors: { server: ['Taken.'] }, shown: ['Taken.'] },
    ])('says $errors as $shown', ({ errors, shown }) => {
        expect(shownFor(errors)).toEqual(shown);
    });

    it('says nothing until the control is touched', () => {
        expect(shownFor({ required: true }, false)).toEqual([]);
    });
});
