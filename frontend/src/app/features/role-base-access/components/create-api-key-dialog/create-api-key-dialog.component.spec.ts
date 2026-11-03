import { DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { CreateApiKeyDialogComponent } from './create-api-key-dialog.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('CreateApiKeyDialogComponent', () => {
    let fixture: ComponentFixture<CreateApiKeyDialogComponent>;
    let httpTesting: HttpTestingController;
    let keydownEvents: Subject<KeyboardEvent>;
    let toastError: ReturnType<typeof vi.fn>;

    afterEach(() => {
        httpTesting.verify();
        TestBed.inject(ActiveOrgService).clear();
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        keydownEvents = new Subject<KeyboardEvent>();
        toastError = vi.fn();
        TestBed.configureTestingModule({
            imports: [CreateApiKeyDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: DialogRef, useValue: { close: vi.fn(), keydownEvents } as unknown as DialogRef },
                { provide: ToastService, useValue: { error: toastError } as unknown as ToastService },
            ],
        });
        httpTesting = TestBed.inject(HttpTestingController);
    });

    function render(activeOrgId: number | null): void {
        TestBed.inject(ActiveOrgService).set(activeOrgId);
        fixture = TestBed.createComponent(CreateApiKeyDialogComponent);
        fixture.detectChanges();
    }

    function nameInput(): HTMLInputElement {
        return fixture.nativeElement.querySelector('app-custom-input input');
    }

    function typeName(name: string): void {
        const input = nameInput();
        input.value = name;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function createButton(): HTMLButtonElement {
        const button = Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('app-button')).find(
            (element) => element.textContent?.trim() === 'Create Key'
        )!;
        return button.querySelector('button')!;
    }

    it('creates the key in the active organization', () => {
        render(7);
        typeName('Deploy Bot');

        createButton().click();

        const request = httpTesting.expectOne('/api/profile/api-keys/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ name: 'Deploy Bot', expires_in_days: 90, org_id: 7 });
    });

    it('cannot create a key without an active organization', () => {
        render(null);
        typeName('Deploy Bot');

        expect(createButton().disabled).toBe(true);
    });

    it('creates the key in the active organization when Enter is pressed in the name field', () => {
        render(7);
        typeName('Deploy Bot');

        const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
        nameInput().dispatchEvent(enter);
        keydownEvents.next(enter);

        const request = httpTesting.expectOne('/api/profile/api-keys/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ name: 'Deploy Bot', expires_in_days: 90, org_id: 7 });
    });

    it('shows the server reason and stays on the form when the key cannot be created', () => {
        render(7);
        typeName('Deploy Bot');
        createButton().click();

        httpTesting.expectOne('/api/profile/api-keys/').flush(
            {
                status_code: 403,
                code: 'org_membership_required',
                message: 'You are not a member of this organization.',
            },
            { status: 403, statusText: 'Forbidden' }
        );
        fixture.detectChanges();

        expect(toastError).toHaveBeenCalledWith('You are not a member of this organization.');
        expect(fixture.nativeElement.querySelector('.title').textContent.trim()).toBe('Create API Key');
        expect(nameInput()).not.toBeNull();
    });

    it('shows a generic error when the failed response has no body', () => {
        render(7);
        typeName('Deploy Bot');
        createButton().click();

        httpTesting.expectOne('/api/profile/api-keys/').flush(null, { status: 502, statusText: 'Bad Gateway' });

        expect(toastError).toHaveBeenCalledWith('Failed to create API key');
    });
});
