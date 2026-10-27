import { HttpRequest, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { Venv, VenvStatus } from '../../models/venv.model';
import { VenvsListPageComponent } from './venvs-list-page.component';

const API_URL = 'http://api/';
const SEARCH_DEBOUNCE_MS = 300;
const POLL_INTERVAL_MS = 2_000;

function venv(id: number, name: string, status: VenvStatus = 'completed'): Venv {
    return { id, name, libs: [], status, error: null, owner: null, created_at: null };
}

describe('VenvsListPageComponent', () => {
    let fixture: ComponentFixture<VenvsListPageComponent>;
    let host: HTMLElement;
    let http: HttpTestingController;

    function listRequests(): HttpRequest<unknown>[] {
        return http.match((request) => request.url === `${API_URL}venvs/`).map((test) => test.request);
    }

    /** The one list request in flight, answered with `venvs`. */
    function answerList(venvs: Venv[]): HttpRequest<unknown> {
        const pending = http.match((request) => request.url === `${API_URL}venvs/`);
        expect(pending).toHaveLength(1);
        pending[0].flush({ count: venvs.length, limit: 100, offset: 0, next: null, previous: null, result: venvs });
        fixture.detectChanges();
        return pending[0].request;
    }

    function type(value: string): void {
        const field = host.querySelector<HTMLInputElement>('.search__input')!;
        field.value = value;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function renderedNames(): string[] {
        return Array.from(host.querySelectorAll('.venv-card__name')).map((node) => node.textContent!.trim());
    }

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );

        TestBed.configureTestingModule({
            imports: [VenvsListPageComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } },
                { provide: PermissionsService, useValue: { can: () => true, canAny: () => true } },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            ],
        });

        fixture = TestBed.createComponent(VenvsListPageComponent);
        host = fixture.nativeElement as HTMLElement;
        http = TestBed.inject(HttpTestingController);
        fixture.detectChanges();
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('asks the backend once typing pauses and shows the venvs it answers with', () => {
        answerList([venv(1, 'alpha'), venv(2, 'beta')]);

        type('al');
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
        type('alp');
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1);
        expect(listRequests()).toHaveLength(0);

        vi.advanceTimersByTime(1);

        // The answer is rendered as it came: a name the search term is not even part of stays
        // on the page, because the narrowing is the backend's and not this component's.
        const request = answerList([venv(3, 'unrelated')]);
        expect(request.params.get('search')).toBe('alp');
        expect(renderedNames()).toEqual(['unrelated']);
    });

    it('sends the chosen sort order right away', () => {
        answerList([venv(1, 'alpha')]);

        host.querySelector<HTMLElement>('.filter-trigger')!.click();
        fixture.detectChanges();
        const descending = Array.from(document.querySelectorAll<HTMLElement>('.filter-menu .menu-item')).find((item) =>
            item.textContent!.includes('Z to A')
        )!;
        descending.click();
        fixture.detectChanges();

        expect(answerList([venv(1, 'alpha')]).params.get('order')).toBe('name_desc');
    });

    it('keeps polling a building venv through the same search', () => {
        answerList([venv(1, 'alpha', 'processing')]);

        type('alp');
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
        answerList([venv(1, 'alpha', 'processing')]);

        vi.advanceTimersByTime(POLL_INTERVAL_MS);

        // A poll without the search would answer with every venv and undo the narrowing.
        expect(answerList([venv(1, 'alpha', 'completed')]).params.get('search')).toBe('alp');
    });
});
