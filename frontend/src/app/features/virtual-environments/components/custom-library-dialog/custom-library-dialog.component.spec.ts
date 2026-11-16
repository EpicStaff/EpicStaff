import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

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
        status: 'completed',
        error: null,
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
        wheel_filename: `acme_utils-${version ?? '0'}-py3-none-any.whl`,
        created_at: '2026-01-02T03:04:05Z',
    };
}

function chosenFile(name: string): File {
    return new File(['payload'], name);
}

describe('CustomLibraryDialogComponent', () => {
    let fixture: ComponentFixture<CustomLibraryDialogComponent>;
    let host: HTMLElement;
    let http: HttpTestingController;
    let close: ReturnType<typeof vi.fn>;
    let toastError: ReturnType<typeof vi.fn>;

    function open(data: CustomLibraryDialogData | null): void {
        TestBed.configureTestingModule({
            imports: [CustomLibraryDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: DialogRef, useValue: { close, keydownEvents: new Subject<KeyboardEvent>() } },
                { provide: DIALOG_DATA, useValue: data },
                { provide: ToastService, useValue: { success: vi.fn(), error: toastError } },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(CustomLibraryDialogComponent);
        host = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    /** Pick files in the dialog's own picker, the way the browser hands them over. */
    function choose(...files: File[]): void {
        const input = host.querySelector<HTMLInputElement>('.custom-library-dialog__file-input')!;
        Object.defineProperty(input, 'files', { value: files, configurable: true });
        input.dispatchEvent(new Event('change'));
        fixture.detectChanges();
    }

    function footerButton(caption: string): HTMLButtonElement {
        return Array.from(host.querySelectorAll<HTMLButtonElement>('.custom-library-dialog__footer button')).find(
            (button) => button.textContent!.includes(caption)
        )!;
    }

    function submit(caption = 'Create Library'): void {
        footerButton(caption).click();
        fixture.detectChanges();
    }

    function rows(): HTMLElement[] {
        return Array.from(host.querySelectorAll<HTMLElement>('.custom-library-dialog__row'));
    }

    function rowTexts(): string[] {
        return rows().map((row) => row.textContent!.replace(/\s+/g, ' ').trim());
    }

    function rowFilenames(): string[] {
        return rows().map((row) => row.querySelector('.custom-library-dialog__file')!.textContent!.trim());
    }

    function removeRow(index: number): void {
        rows()[index].querySelector<HTMLElement>('.custom-library-dialog__icon-btn')!.click();
        fixture.detectChanges();
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

    /** Answers the library re-fetch the dialog makes while the library has no name yet. */
    function answerLibrary(answer: CustomLibrary): void {
        const pending = http.match({ method: 'GET', url: `${LIBRARIES_URL}7/` });
        expect(pending).toHaveLength(1);
        pending[0].flush(answer);
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        close = vi.fn();
        toastError = vi.fn();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('reads the library name off the first chosen file, before anything is sent', () => {
        open(null);

        choose(chosenFile('Acme_Utils-1.0-py3-none-any.whl'));

        expect(host.querySelector('.custom-library-dialog__name-value')!.textContent).toContain('acme-utils');
        expect(host.querySelector('.custom-library-dialog__detected')!.textContent).toContain('Auto-detected');
        expect(http.match(() => true)).toHaveLength(0);
    });

    it('creates the library from the first file and uploads the rest one after another', () => {
        open(null);
        choose(chosenFile('acme_utils-1.0-py3-none-any.whl'), chosenFile('acme-utils-2.0.tar.gz'));

        submit();
        const create = http.expectOne({ method: 'POST', url: LIBRARIES_URL });
        expect(((create.request.body as FormData).get('file') as File).name).toBe('acme_utils-1.0-py3-none-any.whl');
        create.flush(library());
        fixture.detectChanges();

        const upload = uploadRequests();
        expect(upload).toHaveLength(1);
        expect(((upload[0].request.body as FormData).get('file') as File).name).toBe('acme-utils-2.0.tar.gz');

        upload[0].flush(wheel(2, 'declared', null));
        fixture.detectChanges();
        expect(close).toHaveBeenCalledWith(library());
    });

    it.each([
        ['requests-2.32.3-py3-none-any.whl', 'Other library'],
        ['setup.exe', 'Failed'],
        ['acme_utils-1.0-py3-none-any.whl', 'Failed'],
    ])('marks %s as %s and keeps it out of what is sent', (filename, label) => {
        open(null);
        choose(chosenFile('acme_utils-1.0-py3-none-any.whl'), chosenFile(filename));

        expect(rowTexts()[1]).toContain(label);

        submit();
        http.expectOne({ method: 'POST', url: LIBRARIES_URL }).flush(library());
        fixture.detectChanges();

        // The refused file was never uploaded, and the dialog stays open on it.
        expect(uploadRequests()).toHaveLength(0);
        expect(close).not.toHaveBeenCalled();
        answerWheels([wheel(1, 'completed', '1.0')]);
        expect(rowFilenames()).toEqual(['acme_utils-1.0-py3-none-any.whl', filename]);
    });

    it('sends nothing until the changes are saved', () => {
        open({ library: library() });
        answerWheels([wheel(1, 'completed', '1.0')]);

        removeRow(0);
        choose(chosenFile('acme_utils-2.0-py3-none-any.whl'));
        expect(http.match(() => true)).toHaveLength(0);

        submit('Save Changes');
        http.expectOne({ method: 'DELETE', url: `${LIBRARIES_URL}7/wheels/1/` }).flush(null, {
            status: 204,
            statusText: 'No Content',
        });
        fixture.detectChanges();
        uploadRequests()[0].flush(wheel(2, 'completed', '2.0'));
        fixture.detectChanges();

        expect(close).toHaveBeenCalledWith('changed');
    });

    it('applies nothing when the dialog is cancelled', () => {
        open({ library: library() });
        answerWheels([wheel(1, 'completed', '1.0')]);

        removeRow(0);
        footerButton('Cancel').click();
        fixture.detectChanges();

        expect(http.match(() => true)).toHaveLength(0);
        expect(close).toHaveBeenCalledWith(null);
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
});
