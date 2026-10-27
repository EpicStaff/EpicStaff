import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import { Subject } from 'rxjs';

import { PluginLoginOrganizations } from '../../models/plugin-login.model';
import { PluginLoginApiService } from '../../services/plugin-login-api.service';
import { PluginLoginNavigationService } from '../../services/plugin-login-navigation.service';
import { PluginOrgChooserPageComponent } from './plugin-org-chooser-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const BASE = `/api/auth/plugin-authorize/?plugin=weather&state=${'S'.repeat(43)}`;
const PLUGIN = { identifier: 'weather', name: 'Weather', icon_url: '/api/plugin-public/weather/icon/?v=0.3.0' };

describe('PluginOrgChooserPageComponent', () => {
    const navigation = { continueTo: vi.fn() };
    const router = { navigateByUrl: vi.fn() };
    let responses: Subject<PluginLoginOrganizations>[];
    const api = {
        loginOrganizations: vi.fn(() => {
            const response = new Subject<PluginLoginOrganizations>();
            responses.push(response);
            return response;
        }),
    };

    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        responses = [];
    });

    function render(continueParameter: string | null): ComponentFixture<PluginOrgChooserPageComponent> {
        TestBed.configureTestingModule({
            imports: [PluginOrgChooserPageComponent],
            providers: [
                { provide: PluginLoginNavigationService, useValue: navigation },
                { provide: PluginLoginApiService, useValue: api },
                { provide: Router, useValue: router },
                {
                    provide: ActivatedRoute,
                    useValue: {
                        snapshot: {
                            queryParamMap: convertToParamMap(
                                continueParameter === null ? {} : { continue: continueParameter }
                            ),
                        },
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(PluginOrgChooserPageComponent);
        fixture.detectChanges();
        return fixture;
    }

    function answer(fixture: ComponentFixture<PluginOrgChooserPageComponent>, body: PluginLoginOrganizations): void {
        responses[0].next(body);
        responses[0].complete();
        fixture.detectChanges();
    }

    function text(fixture: ComponentFixture<PluginOrgChooserPageComponent>): string {
        return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    /** The only part of the page announced as it changes. */
    function liveStatus(fixture: ComponentFixture<PluginOrgChooserPageComponent>): string {
        const status = (fixture.nativeElement as HTMLElement).querySelector('[aria-live]');
        expect((fixture.nativeElement as HTMLElement).querySelectorAll('[aria-live]').length).toBe(1);
        return (status?.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    function organizationButtons(fixture: ComponentFixture<PluginOrgChooserPageComponent>): HTMLElement[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.chooser__organization'));
    }

    it('loads the plugin’s login organizations and shows one button per organization', () => {
        const fixture = render(BASE);
        expect(liveStatus(fixture)).toContain('Loading your organizations');

        expect(api.loginOrganizations).toHaveBeenCalledExactlyOnceWith('weather');
        answer(fixture, {
            plugin: PLUGIN,
            organizations: [
                { id: 3, name: 'Acme' },
                { id: 5, name: 'Cobalt' },
            ],
        });

        expect(organizationButtons(fixture).map((button) => button.textContent?.trim())).toEqual(['Acme', 'Cobalt']);
        expect(text(fixture)).toContain('Open Weather');
        expect(document.activeElement?.textContent?.trim()).toBe('Open Weather');
        expect((fixture.nativeElement as HTMLElement).querySelector('.chooser__status')?.textContent?.trim()).toBe('');
        expect((fixture.nativeElement as HTMLElement).querySelector('img')?.getAttribute('src')).toBe(PLUGIN.icon_url);
    });

    it('continues with org set to the picked organization, with replace', () => {
        const fixture = render(BASE);
        answer(fixture, { plugin: PLUGIN, organizations: [{ id: 5, name: 'Cobalt' }] });

        organizationButtons(fixture)[0].click();

        expect(navigation.continueTo).toHaveBeenCalledExactlyOnceWith(`${BASE}&org=5`);
    });

    it('replaces an org the request already had', () => {
        const fixture = render(`${BASE}&org=3`);
        answer(fixture, { plugin: PLUGIN, organizations: [{ id: 5, name: 'Cobalt' }] });

        organizationButtons(fixture)[0].click();

        expect(navigation.continueTo).toHaveBeenCalledExactlyOnceWith(`${BASE}&org=5`);
    });

    it('says so when the person can open the plugin in none of their organizations', () => {
        const fixture = render(BASE);
        answer(fixture, { plugin: PLUGIN, organizations: [] });

        expect(liveStatus(fixture)).toContain("You can't open Weather in any of your organizations");
        expect(organizationButtons(fixture)).toEqual([]);
    });

    it('says the plugin is not available on 404', () => {
        const fixture = render(BASE);
        responses[0].error(new HttpErrorResponse({ status: 404, error: { code: 'plugin_not_found' } }));
        fixture.detectChanges();

        expect(liveStatus(fixture)).toContain('This plugin is not available');
        expect(text(fixture)).not.toContain('Try again');
    });

    it('offers to try again after another failure, and loads again', () => {
        const fixture = render(BASE);
        responses[0].error(new HttpErrorResponse({ status: 502, error: 'Bad gateway' }));
        fixture.detectChanges();
        expect(text(fixture)).toContain("Couldn't load your organizations");

        const retry = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('app-button')).find(
            (button) => button.textContent?.trim() === 'Try again'
        ) as HTMLElement;
        retry.click();
        responses[1].next({ plugin: PLUGIN, organizations: [{ id: 3, name: 'Acme' }] });
        fixture.detectChanges();

        expect(api.loginOrganizations).toHaveBeenCalledTimes(2);
        expect(organizationButtons(fixture).map((button) => button.textContent?.trim())).toEqual(['Acme']);
    });

    it.each([
        ['missing', null],
        ['protocol-relative', `//evil.example${BASE}`],
        ['with prompt', `${BASE}&prompt=none`],
    ])('goes to EpicStaff’s start page in-app for a %s continue, and loads nothing', (_name, value) => {
        render(value);

        expect(router.navigateByUrl).toHaveBeenCalledExactlyOnceWith('/', { replaceUrl: true });
        expect(api.loginOrganizations).not.toHaveBeenCalled();
        expect(navigation.continueTo).not.toHaveBeenCalled();
    });
});
