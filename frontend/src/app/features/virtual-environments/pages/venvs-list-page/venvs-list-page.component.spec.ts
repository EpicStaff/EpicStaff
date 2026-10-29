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
    return { id, name, libs: [], status, error: null, owner: null, created_at: null, is_favorite: false };
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
        pending[0].flush({ count: venvs.length, limit: 1000, offset: 0, next: null, previous: null, result: venvs });
        fixture.detectChanges();
        return pending[0].request;
    }

    function type(value: string): void {
        const field = host.querySelector<HTMLInputElement>('.search__input')!;
        field.value = value;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    /** The card's favorite button, named by the label it carries while unstarred. */
    function star(): HTMLElement {
        return host.querySelector<HTMLElement>('.venv-card__icon-btn[aria-label="Add to favorites"]')!;
    }

    function openFilterMenu(): void {
        host.querySelector<HTMLElement>('.filter-trigger')!.click();
        fixture.detectChanges();
    }

    function openSortMenu(): void {
        Array.from(host.querySelectorAll<HTMLElement>('.menu-trigger'))
            .find((trigger) => !trigger.classList.contains('filter-trigger'))!
            .click();
        fixture.detectChanges();
    }

    /** A row of the sort menu, named by part of its label. */
    function menuItem(label: string): HTMLElement {
        return Array.from(document.querySelectorAll<HTMLElement>('.sort-menu .menu-item')).find((item) =>
            item.textContent!.includes(label)
        )!;
    }

    /** A button of the filter panel's footer, named by its caption. */
    function footerButton(caption: string): HTMLElement {
        return Array.from(document.querySelectorAll<HTMLElement>('.filter-menu__footer button')).find((button) =>
            button.textContent!.includes(caption)
        )!;
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

        openSortMenu();
        menuItem('Z to A').click();
        fixture.detectChanges();

        expect(answerList([venv(1, 'alpha')]).params.get('order')).toBe('name_desc');
    });

    it('asks the backend for the favorites only once the filter is saved', () => {
        answerList([venv(1, 'alpha')]);

        openFilterMenu();
        document.querySelector<HTMLElement>('.filter-menu__item')!.click();
        fixture.detectChanges();
        // Ticking alone changes a draft: nothing is requested until Save Changes.
        expect(http.match(() => true)).toHaveLength(0);

        footerButton('Save Changes').click();
        fixture.detectChanges();

        expect(answerList([venv(2, 'starred')]).params.get('is_favorite')).toBe('true');
    });

    it('applies nothing when the filter panel is cancelled', () => {
        answerList([venv(1, 'alpha')]);

        openFilterMenu();
        document.querySelector<HTMLElement>('.filter-menu__item')!.click();
        fixture.detectChanges();
        footerButton('Cancel').click();
        fixture.detectChanges();

        expect(http.match(() => true)).toHaveLength(0);
        expect(host.querySelector('.filter-count')).toBeNull();
    });

    it('fills the star before the request is answered', () => {
        answerList([venv(1, 'alpha')]);

        star().click();
        fixture.detectChanges();

        expect(host.querySelector('.venv-card__icon-btn--accent')).not.toBeNull();
        const request = http.expectOne(`${API_URL}venvs/1/favorite/`);
        expect(request.request.method).toBe('POST');
        request.flush(null);
    });

    it('empties the star again when the request fails', () => {
        answerList([venv(1, 'alpha')]);

        star().click();
        fixture.detectChanges();
        http.expectOne(`${API_URL}venvs/1/favorite/`).flush(null, { status: 500, statusText: 'Server Error' });
        fixture.detectChanges();

        expect(host.querySelector('.venv-card__icon-btn--accent')).toBeNull();
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
