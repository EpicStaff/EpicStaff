import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../../services/config';
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
        open({ venv: storedVenv([{ name: 'requests', version: '2.31.0', specification: '>=2.0,<3.0' }]) });

        expect(cell(0, 'Version').value).toBe('2.31.0');
        expect(cell(0, 'Specification').value).toBe('>=2.0,<3.0');
    });

    it('leaves Version empty for a library the build has not resolved yet', () => {
        open({ venv: storedVenv([{ name: 'requests', version: null, specification: '>=2.0' }]) });

        expect(cell(0, 'Version').value).toBe('');
    });

    it('sends a stored specifier set back unchanged when nothing in the row was edited', () => {
        const specification = '!=1.2,>=1.0,<=1.8';
        open({ venv: storedVenv([{ name: 'requests', version: '1.5', specification }]) });

        save();

        const request = httpMock.expectOne(VENVS_URL + '7/');
        expect(request.request.method).toBe('PATCH');
        expect(request.request.body).toEqual({
            name: 'ml base',
            libs: [{ name: 'requests', version: '1.5', specification }],
        });
        request.flush(storedVenv([{ name: 'requests', version: '1.5', specification }]));
    });

    it.each([
        {
            shape: 'name only: the resolver picks a version',
            version: '',
            specification: '',
            expected: { name: 'requests', version: null, specification: '' },
        },
        {
            shape: 'name and version: that version is pinned',
            version: '2.31.0',
            specification: '',
            expected: { name: 'requests', version: '2.31.0', specification: '' },
        },
        {
            shape: 'name and specification: the resolver picks inside the set',
            version: '',
            specification: '!=1.2,>=1.0,<=1.8',
            expected: { name: 'requests', version: null, specification: '!=1.2,>=1.0,<=1.8' },
        },
        {
            shape: 'name, version and specification: the version wins, the set is kept',
            version: '1.5',
            specification: '!=1.2,>=1.0,<=1.8',
            expected: { name: 'requests', version: '1.5', specification: '!=1.2,>=1.0,<=1.8' },
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

        expect(savedBody().libs).toEqual([{ name: 'requests', version: '2.31.0', specification: '>=2.0' }]);
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

    it('shows the service message when it rejects the version against the specification', () => {
        open({});
        declare('requests', '1.0', '>=2.0');

        save();
        httpMock
            .expectOne(VENVS_URL)
            .flush({ detail: "Version '1.0' does not satisfy specification '>=2.0'" }, { status: 400, statusText: '' });
        fixture.detectChanges();

        const message = (fixture.nativeElement as HTMLElement).querySelector('.venv-dialog__error-message');
        expect(message?.textContent?.trim()).toBe("Version '1.0' does not satisfy specification '>=2.0'");
        expect(close).not.toHaveBeenCalled();
    });
});
