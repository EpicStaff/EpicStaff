import { ChangeDetectionStrategy, Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { ServerErrorsDirective, ServerErrorsRef } from './server-errors.directive';

@Component({
    imports: [ReactiveFormsModule, ServerErrorsDirective],
    // Eager: the template reads control errors, which are not signals and would not refresh an OnPush view.
    changeDetection: ChangeDetectionStrategy.Eager,
    template: `
        <form
            [formGroup]="form"
            [appServerErrors]="form"
            [errorsRef]="errorsRef"
            #serverErrors="serverErrors"
        >
            <input
                class="name"
                formControlName="name"
            />
            @for (message of nameErrors(); track message) {
                <p class="name-error">{{ message }}</p>
            }
            @for (message of serverErrors.formLevelErrors(); track message) {
                <p class="form-error">{{ message }}</p>
            }
        </form>
    `,
})
class SignUpFormComponent {
    readonly form = new FormGroup({ name: new FormControl('') });
    readonly errorsRef = new ServerErrorsRef();

    nameErrors(): string[] {
        return (this.form.controls.name.errors?.['server'] as string[] | undefined) ?? [];
    }
}

describe('ServerErrorsDirective', () => {
    function mount(): ComponentFixture<SignUpFormComponent> {
        const fixture = TestBed.createComponent(SignUpFormComponent);
        fixture.detectChanges();
        return fixture;
    }

    function shown(fixture: ComponentFixture<SignUpFormComponent>, selector: string): string[] {
        fixture.detectChanges();
        return Array.from(fixture.nativeElement.querySelectorAll(selector) as NodeListOf<HTMLElement>).map(
            (element) => element.textContent?.trim() ?? ''
        );
    }

    it('shows field errors under the field and errors naming no field on the form', () => {
        const fixture = mount();

        fixture.componentInstance.errorsRef.setErrors([
            { attr: 'name', detail: 'Name is taken.' },
            { attr: null, detail: 'Sign-up is closed.' },
        ]);

        expect(shown(fixture, '.name-error')).toEqual(['Name is taken.']);
        expect(shown(fixture, '.form-error')).toEqual(['Sign-up is closed.']);
    });

    it('shows an error naming a field the form has no control for on the form, with the field in words', () => {
        const fixture = mount();

        fixture.componentInstance.errorsRef.setErrors([
            { attr: 'ngrok_config.auth_token_secret_id', detail: 'Changing it requires "Use".' },
        ]);

        expect(shown(fixture, '.name-error')).toEqual([]);
        expect(shown(fixture, '.form-error')).toEqual(['Ngrok config: Auth token secret: Changing it requires "Use".']);
    });

    it('drops the field error once the user edits the field', () => {
        const fixture = mount();
        fixture.componentInstance.errorsRef.setErrors([{ attr: 'name', detail: 'Name is taken.' }]);
        expect(shown(fixture, '.name-error')).toEqual(['Name is taken.']);

        const input: HTMLInputElement = fixture.nativeElement.querySelector('input.name');
        input.value = 'Grace';
        input.dispatchEvent(new Event('input'));

        expect(shown(fixture, '.name-error')).toEqual([]);
        expect(fixture.componentInstance.form.valid).toBe(true);
    });

    it('clears every error when the ref is cleared', () => {
        const fixture = mount();
        fixture.componentInstance.errorsRef.setErrors([
            { attr: 'name', detail: 'Name is taken.' },
            { attr: null, detail: 'Sign-up is closed.' },
        ]);
        shown(fixture, '.name-error');

        fixture.componentInstance.errorsRef.clear();

        expect(shown(fixture, '.name-error')).toEqual([]);
        expect(shown(fixture, '.form-error')).toEqual([]);
    });
});
