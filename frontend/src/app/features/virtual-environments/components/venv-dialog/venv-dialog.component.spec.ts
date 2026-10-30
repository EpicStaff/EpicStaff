import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { CreateVenvRequest, Venv, VenvLib } from '../../models/venv.model';
import { VenvDialogComponent, VenvDialogData } from './venv-dialog.component';

const VENVS_URL = '/api/venvs/';

// jsdom has no ResizeObserver; app-button's collapse directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function storedVenv(libs: VenvLib[]): Venv {
    return {
        id: 7,
        name: 'ml base',
        libs,
        status: 'completed',
        error: null,
        owner: null,
        created_at: null,
        is_favorite: false,
    };
}

describe('VenvDialogComponent library rows', () => {
    let fixture: ComponentFixture<VenvDialogComponent>;
    let httpMock: HttpTestingController;
    let close: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        close = vi.fn();
    });

    afterEach(() => {
        httpMock.verify();
        vi.unstubAllGlobals();
    });

    function open(data: VenvDialogData): void {
        TestBed.configureTestingModule({
            imports: [VenvDialogComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: DialogRef, useValue: { close } as unknown as DialogRef },
                { provide: DIALOG_DATA, useValue: data },
                { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(VenvDialogComponent);
        fixture.detectChanges();
    }

    function row(index: number): HTMLElement {
        const rows = (fixture.nativeElement as HTMLElement).querySelectorAll('tbody tr');
        const found = rows.item(index);
        if (!found) throw new Error(`no library row at index ${index}`);
        return found as HTMLElement;
    }

    function cell(index: number, label: 'Library name' | 'Version' | 'Specification'): HTMLInputElement {
        const input = row(index).querySelector(`input[aria-label="${label}"]`);
        if (!input) throw new Error(`no "${label}" input in row ${index}`);
        return input as HTMLInputElement;
    }

    function type(index: number, label: 'Library name' | 'Version' | 'Specification', value: string): void {
        const input = cell(index, label);
        input.value = value;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function addRow(): void {
        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.venv-dialog__add-lib')?.click();
        fixture.detectChanges();
    }

    function save(): void {
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('app-button[type="primary"] button')
            ?.click();
        fixture.detectChanges();
    }

    function savedBody(): CreateVenvRequest {
        const request: TestRequest = httpMock.expectOne(VENVS_URL);
        return request.request.body as CreateVenvRequest;
    }

    function nameVenv(value: string): void {
        const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('input#venv-dialog-name');
        if (!input) throw new Error('no venv name input');
        input.value = value;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    // One library declared the way a user declares it: name first, then whatever of the two
    // version fields they care about.
    function declare(name: string, version: string, specification: string): void {
        nameVenv('ml base');
        addRow();
        type(0, 'Library name', name);
        if (version) type(0, 'Version', version);
        if (specification) type(0, 'Specification', specification);
    }

    it('fills Version with the installed version and Specification with the stored specifier set', () => {
        open({
            venv: storedVenv([{ name: 'requests', version: '2.31.0', specification: '>=2.0,<3.0', description: null }]),
        });

        expect(cell(0, 'Version').value).toBe('2.31.0');
        expect(cell(0, 'Specification').value).toBe('>=2.0,<3.0');
    });

    it('leaves Version empty for a library the build has not resolved yet', () => {
        open({ venv: storedVenv([{ name: 'requests', version: null, specification: '>=2.0', description: null }]) });

        expect(cell(0, 'Version').value).toBe('');
    });

    it('sends a stored specifier set back unchanged when nothing in the row was edited', () => {
        const specification = '!=1.2,>=1.0,<=1.8';
        open({ venv: storedVenv([{ name: 'requests', version: '1.5', specification, description: null }]) });

        save();

        const request = httpMock.expectOne(VENVS_URL + '7/');
        expect(request.request.method).toBe('PATCH');
        expect(request.request.body).toEqual({
            name: 'ml base',
            libs: [{ name: 'requests', version: '1.5', specification, description: null }],
        });
        request.flush(storedVenv([{ name: 'requests', version: '1.5', specification, description: null }]));
    });

    it.each([
        {
            shape: 'name only: the resolver picks a version',
            version: '',
            specification: '',
            expected: { name: 'requests', version: null, specification: '', description: null },
        },
        {
            shape: 'name and version: that version is pinned',
            version: '2.31.0',
            specification: '',
            expected: { name: 'requests', version: '2.31.0', specification: '', description: null },
        },
        {
            shape: 'name and specification: the resolver picks inside the set',
            version: '',
            specification: '!=1.2,>=1.0,<=1.8',
            expected: { name: 'requests', version: null, specification: '!=1.2,>=1.0,<=1.8', description: null },
        },
        {
            shape: 'name, version and specification: the version wins, the set is kept',
            version: '1.5',
            specification: '!=1.2,>=1.0,<=1.8',
            expected: { name: 'requests', version: '1.5', specification: '!=1.2,>=1.0,<=1.8', description: null },
        },
    ])('posts $shape', ({ version, specification, expected }) => {
        open({});
        declare('requests', version, specification);

        save();

        expect(savedBody().libs).toEqual([expected]);
    });

    it('trims the padding the user left around a value', () => {
        open({});
        declare('  requests  ', '2.31.0', '  >=2.0  ');

        save();

        expect(savedBody().libs).toEqual([
            { name: 'requests', version: '2.31.0', specification: '>=2.0', description: null },
        ]);
    });

    it.each(['>=1.0', '!=1.2,>=1.0,<=1.8', '==1.2.*', '~=1.4.2', '>=1.0, <2.0'])(
        'accepts the specifier set %s',
        (specification) => {
            open({});
            declare('requests', '', specification);

            save();

            expect(savedBody().libs[0].specification).toBe(specification.trim());
        }
    );

    it.each(['1.0', '>=', 'latest', '=>1.0', '>=1.0,', '>=1.0 <2.0'])(
        'refuses to save the specifier set %s',
        (specification) => {
            open({});
            declare('requests', '', specification);

            save();

            httpMock.expectNone(VENVS_URL);
            expect(cell(0, 'Specification').classList).toContain('venv-dialog__cell-input--invalid');
        }
    );

    it('refuses to save a version that is not a version', () => {
        open({});
        declare('requests', '', '');
        type(0, 'Version', 'newest');

        save();

        httpMock.expectNone(VENVS_URL);
        expect(cell(0, 'Version').classList).toContain('venv-dialog__cell-input--invalid');
    });

    it('toasts the service message when it rejects the version against the specification', () => {
        open({});
        declare('requests', '1.0', '>=2.0');

        save();
        httpMock
            .expectOne(VENVS_URL)
            .flush({ detail: "Version '1.0' does not satisfy specification '>=2.0'" }, { status: 400, statusText: '' });

        expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith(
            "Version '1.0' does not satisfy specification '>=2.0'"
        );
        expect(close).not.toHaveBeenCalled();
    });

    it('toasts why a library change was refused for a venv that code reading secrets runs in', () => {
        const message =
            'libs: Changing code that reads secrets, or what it runs with, requires the "Use" permission on Secrets. ' +
            'The existing value was left unchanged. Ask an organization admin to grant it.';
        open({ venv: storedVenv([{ name: 'requests', specification: '', version: '2.31.0', description: null }]) });
        type(0, 'Version', '2.32.0');

        save();
        httpMock
            .expectOne(`${VENVS_URL}7/`)
            .flush({ status_code: 400, code: 'invalid', message }, { status: 400, statusText: 'Bad Request' });

        expect(TestBed.inject(ToastService).error).toHaveBeenCalledExactlyOnceWith(message);
        expect(close).not.toHaveBeenCalled();
    });
});
