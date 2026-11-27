import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GeneralPreferences, GetMeResponse } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from '../../services/auth/testing/current-user-fixtures';
import { PREFERENCES_SAVE_DEBOUNCE_MS, UserPreferencesService } from '../../services/auth/user-preferences.service';
import { ConfigService } from '../../services/config';
import { UserDatePipe } from './user-date.pipe';

const GENERAL_URL = '/api/profile/preferences/general/';

@Component({
    imports: [UserDatePipe],
    template: `<span>{{ value() | userDate: format() }}</span>`,
})
class DateHostComponent {
    readonly value = signal<string | null>('2026-07-01T12:00:00Z');
    readonly format = signal('HH:mm');
}

describe('UserDatePipe', () => {
    let httpMock: HttpTestingController;

    beforeEach(() => {
        // Timers only: faking Date also swaps in its own Intl.DateTimeFormat, which the browser-zone stub can't reach.
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    function signIn(general: GeneralPreferences): void {
        const user = memberOf(ORGANIZATION_A);
        const signedIn: GetMeResponse = { ...user, preferences: { ...user.preferences, general } };
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(signedIn);
    }

    function render(value: string | null, format: string) {
        const fixture = TestBed.createComponent(DateHostComponent);
        fixture.componentInstance.value.set(value);
        fixture.componentInstance.format.set(format);
        fixture.detectChanges();
        const shown = (): string => (fixture.nativeElement as HTMLElement).textContent!.trim();
        return { fixture, shown };
    }

    it('formats in the display zone not the browser zone', () => {
        signIn({ display_timezone: 'America/New_York', default_timezone: null });

        expect(render('2026-07-01T12:00:00Z', 'HH:mm').shown()).toBe('08:00');
    });

    it('follows the browser zone when the preference is empty', () => {
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
            timeZone: 'Asia/Tokyo',
        } as Intl.ResolvedDateTimeFormatOptions);
        signIn({ display_timezone: null, default_timezone: null });

        expect(render('2026-07-01T12:00:00Z', 'HH:mm').shown()).toBe('21:00');
    });

    it('shows the new zone at once when the display timezone changes', () => {
        signIn({ display_timezone: 'America/New_York', default_timezone: null });
        const { fixture, shown } = render('2026-07-01T12:00:00Z', 'MMM d, HH:mm');
        expect(shown()).toBe('Jul 1, 08:00');

        TestBed.inject(UserPreferencesService).patchSection('general', { display_timezone: 'Asia/Tokyo' });
        fixture.detectChanges();

        expect(shown()).toBe('Jul 1, 21:00');
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);
        httpMock
            .expectOne({ method: 'PATCH', url: GENERAL_URL })
            .flush({ display_timezone: 'Asia/Tokyo', default_timezone: null });
    });

    it('shows nothing for a missing date, as the date pipe does', () => {
        signIn({ display_timezone: 'America/New_York', default_timezone: null });

        expect(render(null, 'HH:mm').shown()).toBe('');
        expect(render('', 'HH:mm').shown()).toBe('');
    });
});
