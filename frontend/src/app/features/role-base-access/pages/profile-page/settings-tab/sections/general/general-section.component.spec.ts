import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GeneralPreferences, GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../../../../../services/auth/profile.service';
import {
    API_URL,
    memberOf,
    ORGANIZATION_A,
    PROFILE_URL,
} from '../../../../../../../services/auth/testing/current-user-fixtures';
import { PREFERENCES_SAVE_DEBOUNCE_MS } from '../../../../../../../services/auth/user-preferences.service';
import { ConfigService } from '../../../../../../../services/config';
import { GeneralSectionComponent } from './general-section.component';

const GENERAL_URL = '/api/profile/preferences/general/';
const BROWSER_ZONE = 'Asia/Tokyo';
const BROWSER_OPTION = 'Use browser timezone (Asia/Tokyo)';

describe('GeneralSectionComponent', () => {
    let fixture: ComponentFixture<GeneralSectionComponent>;
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
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => element.remove());
    });

    function render(general: GeneralPreferences): void {
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
            timeZone: BROWSER_ZONE,
        } as Intl.ResolvedDateTimeFormatOptions);
        const user = memberOf(ORGANIZATION_A);
        const signedIn: GetMeResponse = { ...user, preferences: { ...user.preferences, general } };
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(signedIn);

        fixture = TestBed.createComponent(GeneralSectionComponent);
        fixture.detectChanges();
    }

    function referencedText(ids: string | null): string | undefined {
        return ids === null
            ? undefined
            : (fixture.nativeElement as HTMLElement).querySelector(`#${ids}`)?.textContent?.trim();
    }

    /** The group the visible label names, found the way assistive tech finds it. */
    function group(label: string): HTMLElement {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('[role="group"][aria-labelledby]')
        ).find((candidate) => referencedText(candidate.getAttribute('aria-labelledby')) === label)!;
    }

    function picker(label: string): HTMLElement {
        return group(label).querySelector('app-timezone-selector')!;
    }

    function shownZone(label: string): string {
        return picker(label).querySelector('.tz-selector__text')!.textContent!.trim();
    }

    function pick(label: string, zone: string): void {
        picker(label).querySelector<HTMLButtonElement>('.tz-selector__btn')!.click();
        fixture.detectChanges();
        const option = Array.from(document.querySelectorAll<HTMLElement>('.tz-selector__option')).find(
            (candidate) => candidate.querySelector('.tz-selector__iana')?.textContent?.trim() === zone
        )!;
        option.click();
        fixture.detectChanges();
    }

    it('names each picker by its label and describes it by its hint', () => {
        render({ display_timezone: null, default_timezone: null });

        expect(picker('Display timezone')).not.toBeNull();
        expect(referencedText(group('Display timezone').getAttribute('aria-describedby'))).toBe(
            'Dates and times across the app are shown in it'
        );
        expect(referencedText(group('Default timezone').getAttribute('aria-describedby'))).toBe(
            'Used when you create schedule triggers'
        );
    });

    it('shows a null preference as "Use browser timezone" picked, so it reads as following the browser', () => {
        render({ display_timezone: null, default_timezone: 'Europe/Kyiv' });

        expect(shownZone('Display timezone')).toBe(BROWSER_OPTION);
        expect(shownZone('Default timezone')).toContain('Europe/Kyiv');
        expect(shownZone('Default timezone')).not.toContain(BROWSER_ZONE);
    });

    it.each([
        { label: 'Display timezone', preference: 'display_timezone' },
        { label: 'Default timezone', preference: 'default_timezone' },
    ])('picking "Use browser timezone" saves $preference as null', ({ label, preference }) => {
        render({ display_timezone: 'Europe/Kyiv', default_timezone: 'Europe/Kyiv' });

        pick(label, BROWSER_OPTION);
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);

        const request = httpMock.expectOne({ method: 'PATCH', url: GENERAL_URL });
        expect(request.request.body).toEqual({ [preference]: null });
        request.flush({ display_timezone: 'Europe/Kyiv', default_timezone: 'Europe/Kyiv', [preference]: null });
        fixture.detectChanges();
        expect(shownZone(label)).toBe(BROWSER_OPTION);
    });

    it.each([
        { label: 'Display timezone', preference: 'display_timezone' },
        { label: 'Default timezone', preference: 'default_timezone' },
    ])('saves $preference through the general section', ({ label, preference }) => {
        render({ display_timezone: null, default_timezone: null });

        pick(label, 'America/New_York');
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);

        const request = httpMock.expectOne({ method: 'PATCH', url: GENERAL_URL });
        expect(request.request.body).toEqual({ [preference]: 'America/New_York' });
        request.flush({ display_timezone: null, default_timezone: null, [preference]: 'America/New_York' });
        fixture.detectChanges();
        expect(shownZone(label)).toContain('America/New_York');
    });

    it('puts the stored zone back when the save fails', () => {
        render({ display_timezone: 'Europe/Kyiv', default_timezone: null });

        pick('Display timezone', 'America/New_York');
        expect(shownZone('Display timezone')).toContain('America/New_York');
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);
        httpMock
            .expectOne({ method: 'PATCH', url: GENERAL_URL })
            .flush({ display_timezone: ['Unknown timezone.'] }, { status: 400, statusText: 'Bad Request' });
        fixture.detectChanges();

        expect(shownZone('Display timezone')).toContain('Europe/Kyiv');
    });

    it('saves nothing when the stored zone is picked again', () => {
        render({ display_timezone: 'Europe/Kyiv', default_timezone: null });

        pick('Display timezone', 'Europe/Kyiv');
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);

        httpMock.expectNone({ method: 'PATCH', url: GENERAL_URL });
    });
});
