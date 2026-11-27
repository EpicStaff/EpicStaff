import { DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { ConfigService } from '../../../../services/config';
import { AddSecretDialogComponent } from './add-secret-dialog.component';

const API_URL = 'http://api/';

/** jsdom has no ResizeObserver, which the dialog's buttons use to collapse their labels. */
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('AddSecretDialogComponent', () => {
    let fixture: ComponentFixture<AddSecretDialogComponent>;
    let httpTesting: HttpTestingController;
    const dialogRef = { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() };

    const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
    const nameErrors = (): string[] =>
        Array.from(host().querySelectorAll('.validation-errors__item')).map((item) => item.textContent!.trim());

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        dialogRef.close.mockReset();
        TestBed.configureTestingModule({
            imports: [AddSecretDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: DialogRef, useValue: dialogRef },
            ],
        });
        httpTesting = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(AddSecretDialogComponent);
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    function type(fieldIndex: number, value: string): void {
        const input = host().querySelectorAll<HTMLElement>('input, textarea')[fieldIndex] as
            | HTMLInputElement
            | HTMLTextAreaElement;
        input.value = value;
        input.dispatchEvent(new Event('input'));
        input.dispatchEvent(new Event('blur'));
        fixture.detectChanges();
    }

    function submitButton(): HTMLButtonElement {
        return Array.from(host().querySelectorAll<HTMLButtonElement>('app-button button')).find((button) =>
            button.textContent!.includes('Add Secret')
        )!;
    }

    function clickSubmit(): void {
        submitButton().click();
        fixture.detectChanges();
    }

    it.each([
        ['letters and spaces', 'OpenAI API Key'],
        ['non-Latin letters, digits, _ - and .', 'Ключ_API-v2.0'],
    ])('creates a secret with a name of %s', (_case, name) => {
        type(0, name);
        type(1, 'sk-value');
        clickSubmit();

        const request = httpTesting.expectOne({ method: 'POST', url: `${API_URL}secrets/` });
        expect(request.request.body).toEqual({ name, value: 'sk-value' });
    });

    it.each([
        ['an f-string expression', "{__import__('os')}"],
        ['parentheses', 'a(b)'],
        ['a plus', 'a+b'],
        ['a double quote', 'A"B'],
        ['a single quote', "A'B"],
        ['a backslash', 'A\\B'],
        ['a colon', 'A:B'],
        ['a slash', 'A/B'],
        ['a less-than sign', 'A<B'],
        ['a tab', 'A\tB'],
    ])('rejects a typed name with %s, says what is allowed, and sends nothing', (_case, name) => {
        type(0, name);
        type(1, 'sk-value');
        clickSubmit();

        expect(nameErrors()).toEqual(['Only letters, digits, spaces, and _ - . are allowed.']);
        expect(submitButton().disabled).toBe(true);
        httpTesting.expectNone(`${API_URL}secrets/`);
        expect(dialogRef.close).not.toHaveBeenCalled();
    });

    it('rejects a name of only spaces before sending it', () => {
        type(0, '   ');
        type(1, 'sk-value');
        clickSubmit();

        expect(nameErrors()).toEqual(['Value cannot be blank string.']);
        expect(submitButton().disabled).toBe(true);
        httpTesting.expectNone(`${API_URL}secrets/`);
    });

    // A text input drops typed line breaks, so the newline is set on the form control the field is bound to.
    it('rejects a name with a newline', () => {
        type(0, 'A');
        type(1, 'sk-value');
        fixture.componentInstance.form.controls['name'].setValue('A\nB');
        fixture.detectChanges();
        clickSubmit();

        expect(nameErrors()).toEqual(['Only letters, digits, spaces, and _ - . are allowed.']);
        httpTesting.expectNone(`${API_URL}secrets/`);
    });
});
