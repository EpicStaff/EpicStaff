import { DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from '../../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../../services/config';
import { FlowSettingsService } from '../../services/flow-settings.service';
import { FlowViewOverrideService } from '../../services/flow-view-override.service';
import { FlowViewOverride } from '../../services/flow-view-settings-api.service';
import { FlowSettingsPanelComponent } from './flow-settings-panel.component';

const VIEW_SETTINGS_URL = '/api/graphs/5/my-view-settings/';
const ACCOUNT_ZONE = 'Europe/Kyiv';
const USE_MY_DEFAULT = 'Use my default (Europe/Kyiv)';

describe('FlowSettingsPanelComponent', () => {
    let fixture: ComponentFixture<FlowSettingsPanelComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        // jsdom has no ResizeObserver; the reset button watches its own width for a cut-short label.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                { provide: DialogRef, useValue: { close: vi.fn() } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        // The header's close icon loads its svg; only the view-settings requests are under test.
        http.match((request) => request.url.startsWith('assets/'));
        http.verify();
        vi.unstubAllGlobals();
        document.querySelectorAll('.cdk-overlay-container').forEach((element) => element.remove());
    });

    /** Opens the panel on flow 5, holding `stored`, for a user whose account default timezone is Europe/Kyiv. */
    function render(stored: FlowViewOverride = {}): void {
        const user = memberOf(ORGANIZATION_A);
        const signedIn: GetMeResponse = {
            ...user,
            preferences: {
                ...user.preferences,
                general: { ...user.preferences.general, default_timezone: ACCOUNT_ZONE },
            },
        };
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush(signedIn);
        TestBed.inject(FlowViewOverrideService).load(5);
        http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL }).flush({ settings: stored });
        fixture = TestBed.createComponent(FlowSettingsPanelComponent);
        fixture.detectChanges();
    }

    function toggle(label: string): HTMLInputElement {
        const row = fixture.debugElement
            .queryAll(By.css('.form-section--toggle'))
            .find((section) => section.nativeElement.textContent.includes(label))!;
        return row.nativeElement.querySelector('input[type="checkbox"]');
    }

    function resetButton(): HTMLButtonElement | null {
        return (
            fixture.debugElement
                .queryAll(By.css('.dialog-footer button'))
                .find((button) => button.nativeElement.textContent.includes('Reset to my defaults'))?.nativeElement ??
            null
        );
    }

    function shownZone(): string {
        return fixture.nativeElement.querySelector('app-timezone-selector .tz-selector__text').textContent.trim();
    }

    function pickZone(label: string): void {
        fixture.nativeElement.querySelector('app-timezone-selector .tz-selector__btn').click();
        fixture.detectChanges();
        const option = Array.from(document.querySelectorAll<HTMLElement>('.tz-selector__option')).find(
            (element) => element.querySelector('.tz-selector__iana')?.textContent?.trim() === label
        )!;
        option.click();
        fixture.detectChanges();
    }

    it.each([
        ['Always show node numbers', 'alwaysShowNodeNumbers', 'always_show_node_numbers'],
        ['Highlight unused nodes', 'highlightUnusedNodes', 'highlight_unused_nodes'],
    ] as const)('"%s" changes the %s setting of this flow only', (label, setting, key) => {
        render();
        const settings = TestBed.inject(FlowSettingsService);

        toggle(label).click();
        fixture.detectChanges();

        expect(settings[setting]()).toBe(true);
        const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
        expect(save.request.body).toEqual({ settings: { [key]: true } });
    });

    it("offers a reset only once the flow has settings of its own, and the reset brings back the account's", () => {
        render();
        expect(resetButton()).toBeNull();

        toggle('Highlight unused nodes').click();
        fixture.detectChanges();
        http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }).flush({ settings: { highlight_unused_nodes: true } });
        pickZone('Asia/Tokyo');
        http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }).flush({
            settings: { highlight_unused_nodes: true, default_timezone: 'Asia/Tokyo' },
        });
        expect(resetButton()).not.toBeNull();

        resetButton()!.click();
        fixture.detectChanges();

        http.expectOne({ method: 'DELETE', url: VIEW_SETTINGS_URL }).flush(null, { status: 204, statusText: '' });
        expect(toggle('Highlight unused nodes').checked).toBe(false);
        expect(shownZone()).toBe(USE_MY_DEFAULT);
        expect(resetButton()).toBeNull();
    });

    describe('timezone for new schedule triggers', () => {
        it("shows the account's zone while the flow has none of its own", () => {
            render();

            expect(shownZone()).toBe(USE_MY_DEFAULT);
        });

        it("shows the flow's own zone once it is loaded", () => {
            render({ default_timezone: 'Asia/Tokyo' });

            expect(shownZone()).toContain('Asia/Tokyo');
        });

        it("saves a picked zone as this flow's own", () => {
            render({ arrow_colors: false });

            pickZone('Asia/Tokyo');

            const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(save.request.body).toEqual({ settings: { arrow_colors: false, default_timezone: 'Asia/Tokyo' } });
            save.flush({ settings: { arrow_colors: false, default_timezone: 'Asia/Tokyo' } });
            expect(TestBed.inject(FlowSettingsService).newScheduleZone()).toBe('Asia/Tokyo');
        });

        it(`"Use my default" removes the flow's zone and keeps its other settings`, () => {
            render({ arrow_colors: false, default_timezone: 'Asia/Tokyo' });

            pickZone(USE_MY_DEFAULT);

            const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(save.request.body).toEqual({ settings: { arrow_colors: false } });
            save.flush({ settings: { arrow_colors: false } });
            expect(shownZone()).toBe(USE_MY_DEFAULT);
            expect(TestBed.inject(FlowSettingsService).newScheduleZone()).toBe(ACCOUNT_ZONE);
        });

        it("picking the account's own zone leaves the flow without one", () => {
            render({ default_timezone: 'Asia/Tokyo' });

            pickZone(ACCOUNT_ZONE);

            http.expectOne({ method: 'DELETE', url: VIEW_SETTINGS_URL }).flush(null, { status: 204, statusText: '' });
            expect(resetButton()).toBeNull();
            expect(shownZone()).toBe(USE_MY_DEFAULT);
        });
    });
});
