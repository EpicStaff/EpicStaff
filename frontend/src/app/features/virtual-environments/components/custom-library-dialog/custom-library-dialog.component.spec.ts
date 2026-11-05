import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, Subject } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { CustomLibrary, Wheel, WheelStatus } from '../../models/custom-library.model';
import { CustomLibraryDialogComponent, CustomLibraryDialogData } from './custom-library-dialog.component';

const API_URL = 'http://api/';
const LIBRARIES_URL = `${API_URL}custom-libraries/`;
const POLL_INTERVAL_MS = 2_000;

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function library(name: string | null = 'acme-utils'): CustomLibrary {
    return {
        id: 7,
        name,
        owner: null,
        created_at: '2026-01-02T03:04:05Z',
        updated_at: '2026-01-02T03:04:05Z',
    };
}

function wheel(id: number, status: WheelStatus, version: string | null): Wheel {
    return {
        id,
        version,
        status,
        error: null,
        source_filename: null,
        wheel_filename: 'acme_utils-1.0-py3-none-any.whl',
        created_at: '2026-01-02T03:04:05Z',
    };
}

function wheelFile(name: string): File {
    return new File(['payload'], name);
}

describe('CustomLibraryDialogComponent', () => {
    let fixture: ComponentFixture<CustomLibraryDialogComponent>;
    let host: HTMLElement;
    let http: HttpTestingController;
    let close: ReturnType<typeof vi.fn>;
    let toastError: ReturnType<typeof vi.fn>;
    let confirmation: Subject<boolean>;

    function open(data: CustomLibraryDialogData | null): void {
        TestBed.configureTestingModule({
            imports: [CustomLibraryDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: DialogRef, useValue: { close } },
                { provide: DIALOG_DATA, useValue: data },
                { provide: ToastService, useValue: { success: vi.fn(), error: toastError } },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
                {
                    provide: ConfirmationDialogService,
                    useValue: { confirmDelete: (): Observable<boolean> => confirmation },
                },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(CustomLibraryDialogComponent);
        host = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    /** Pick files in the dialog's file input, the way the browser hands them over. */
    function choose(...files: File[]): void {
        const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
        Object.defineProperty(input, 'files', { value: files, configurable: true });
        input.dispatchEvent(new Event('change'));
        fixture.detectChanges();
    }

    function headerButton(caption: string): HTMLElement {
        return Array.from(host.querySelectorAll<HTMLElement>('.custom-library-dialog__header-actions button')).find(
            (button) => button.textContent!.includes(caption)
        )!;
    }

    function uploadRequests(): TestRequest[] {
        return http.match((request) => request.method === 'POST' && request.url === `${LIBRARIES_URL}7/wheels/`);
    }

    function answerWheels(wheels: Wheel[]): void {
        const pending = http.match({ method: 'GET', url: `${LIBRARIES_URL}7/wheels/` });
        expect(pending).toHaveLength(1);
        pending[0].flush(wheels);
        fixture.detectChanges();
    }

    /** Answers the library re-fetch `refreshLibraryIfUnnamed` makes once wheels are (re)loaded
     *  while the library has no name yet. */
    function answerLibrary(answer: CustomLibrary): void {
        const pending = http.match({ method: 'GET', url: `${LIBRARIES_URL}7/` });
        expect(pending).toHaveLength(1);
        pending[0].flush(answer);
        fixture.detectChanges();
    }

    function rowTexts(): string[] {
        return Array.from(host.querySelectorAll('.custom-library-dialog__row')).map((row) =>
            row.textContent!.replace(/\s+/g, ' ').trim()
        );
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        close = vi.fn();
        toastError = vi.fn();
        confirmation = new Subject<boolean>();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('creates a library from the first wheel chosen, named by the backend', () => {
        open(null);
        choose(wheelFile('acme_utils-1.0-py3-none-any.whl'));

        headerButton('Create').click();
        fixture.detectChanges();

        const request = http.expectOne({ method: 'POST', url: LIBRARIES_URL });
        const body = request.request.body as FormData;
        expect((body.get('file') as File).name).toBe('acme_utils-1.0-py3-none-any.whl');
        request.flush(library());

        expect(close).toHaveBeenCalledWith(library());
    });

    it('uploads the wheels chosen after the first one after another, not all at once', () => {
        open(null);
        choose(wheelFile('acme_utils-1.0-py3-none-any.whl'), wheelFile('acme_utils-2.0.tar.gz'));

        headerButton('Create').click();
        fixture.detectChanges();
        const createRequest = http.expectOne({ method: 'POST', url: LIBRARIES_URL });
        expect((createRequest.request.body as FormData).get('file')).toBeTruthy();
        createRequest.flush(library());
        fixture.detectChanges();

        const second = uploadRequests();
        expect(second).toHaveLength(1);
        expect(((second[0].request.body as FormData).get('file') as File).name).toBe('acme_utils-2.0.tar.gz');

        second[0].flush(wheel(2, 'declared', null));
        fixture.detectChanges();
        expect(close).toHaveBeenCalledWith(library());
    });

    it('keeps the created library open when a later wheel fails to upload', () => {
        open(null);
        choose(wheelFile('acme_utils-1.0-py3-none-any.whl'), wheelFile('acme_utils-2.0.tar.gz'));

        headerButton('Create').click();
        fixture.detectChanges();
        http.expectOne({ method: 'POST', url: LIBRARIES_URL }).flush(library());
        fixture.detectChanges();
        uploadRequests()[0].flush({ detail: 'Broken archive' }, { status: 400, statusText: 'Bad Request' });
        fixture.detectChanges();

        expect(close).not.toHaveBeenCalled();
        expect(toastError.mock.calls[0][0]).toContain('acme_utils-2.0.tar.gz');
        // The dialog now manages the library it created: its name is the title, and its versions
        // are read back from the backend.
        expect(host.querySelector('.custom-library-dialog__title')!.textContent).toContain('acme-utils');
        answerWheels([]);
    });

    it('refuses a file that is neither a wheel nor a source archive', () => {
        open(null);

        choose(wheelFile('notes.txt'));

        expect(rowTexts()).toEqual([]);
        expect(toastError.mock.calls[0][0]).toContain('notes.txt');
    });

    it('accepts a source archive to create the library, named later by a build', () => {
        open(null);

        choose(wheelFile('acme-utils-1.0.0.tar.gz'));

        expect(rowTexts()).toEqual(['acme-utils-1.0.0.tar.gz']);
        expect(toastError).not.toHaveBeenCalled();
    });

    it('shows the title as pending and picks it up once a build names the library', () => {
        open({ library: library(null) });
        answerWheels([wheel(1, 'declared', null)]);
        expect(host.querySelector('.custom-library-dialog__title')!.textContent).toContain('Naming pending');

        // Still unnamed: the build has not finished, so the re-fetch changes nothing.
        answerLibrary(library(null));
        expect(host.querySelector('.custom-library-dialog__title')!.textContent).toContain('Naming pending');

        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        answerWheels([wheel(1, 'completed', '1.0.0')]);
        answerLibrary(library());

        expect(host.querySelector('.custom-library-dialog__title')!.textContent).toContain('acme-utils');
    });

    it('asks again while a version is still being built', () => {
        open({ library: library() });
        answerWheels([wheel(1, 'processing', null)]);

        expect(rowTexts()[0]).toContain('Building');

        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        answerWheels([wheel(1, 'completed', '1.0')]);

        expect(rowTexts()[0]).toContain('1.0');
        // Nothing is left building, so the next tick asks for nothing.
        vi.advanceTimersByTime(POLL_INTERVAL_MS);
        http.expectNone({ method: 'GET', url: `${LIBRARIES_URL}7/wheels/` });
    });

    it('deletes a version only after the confirmation is answered', () => {
        open({ library: library() });
        answerWheels([wheel(1, 'completed', '1.0')]);

        host.querySelector<HTMLElement>('.custom-library-dialog__icon-btn')!.click();
        fixture.detectChanges();
        expect(http.match((request) => request.method === 'DELETE')).toHaveLength(0);

        confirmation.next(true);
        confirmation.complete();
        fixture.detectChanges();
        http.expectOne({ method: 'DELETE', url: `${LIBRARIES_URL}7/wheels/1/` }).flush(null, {
            status: 204,
            statusText: 'No Content',
        });
        fixture.detectChanges();

        answerWheels([]);
        expect(rowTexts()).toEqual([]);
    });
});
