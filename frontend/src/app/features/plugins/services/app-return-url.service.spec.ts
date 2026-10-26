import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { APP_STORAGE, AppStorageService } from '@shared/services';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { providePluginsStorages } from '../plugins.providers';
import { AppReturnUrlService } from './app-return-url.service';

describe('AppReturnUrlService', () => {
    const defaultRoute = signal('/agents');

    function create(): AppReturnUrlService {
        TestBed.configureTestingModule({
            providers: [
                { provide: APP_STORAGE, useExisting: AppReturnUrlService, multi: true },
                { provide: PermissionsService, useValue: { resolveDefaultRoute: () => defaultRoute() } },
            ],
        });
        return TestBed.inject(AppReturnUrlService);
    }

    beforeEach(() => defaultRoute.set('/agents'));

    afterEach(() => {
        sessionStorage.clear();
        vi.restoreAllMocks();
    });

    it("falls back to the user's default page while no EpicStaff page was shown, and follows it", () => {
        const service = create();

        expect(service.url()).toBe('/agents');
        defaultRoute.set('/workspace/main');
        expect(service.url()).toBe('/workspace/main');
    });

    it('remembers the last EpicStaff page with its query', () => {
        const service = create();

        service.record('/flows/my');
        service.record('/storage/files?folder=7');

        expect(service.url()).toBe('/storage/files?folder=7');
    });

    it.each(['/plugins/asg', '/plugins/asg/projects?tab=1', '//evil.example.com/flows', 'https://evil.example.com'])(
        'ignores %s',
        (url) => {
            const service = create();
            service.record('/flows/my');

            service.record(url);

            expect(service.url()).toBe('/flows/my');
        }
    );

    it('survives a reload of the page in the same tab', () => {
        create().record('/tools/mcp');

        TestBed.resetTestingModule();

        expect(create().url()).toBe('/tools/mcp');
    });

    it('does not take a stored app page or a foreign address back', () => {
        sessionStorage.setItem('epicstaff.appReturnUrl', '//evil.example.com');

        expect(create().url()).toBe('/agents');
    });

    it('is one of the storages an organization switch or a logout clears', () => {
        expect(providePluginsStorages()).toContainEqual({
            provide: APP_STORAGE,
            useExisting: AppReturnUrlService,
            multi: true,
        });
    });

    it('is forgotten when cleared, in this tab and after a reload', () => {
        const service = create();
        service.record('/tools/mcp');

        TestBed.inject(AppStorageService).clearAll();

        expect(service.url()).toBe('/agents');
        TestBed.resetTestingModule();
        expect(create().url()).toBe('/agents');
    });

    it('works without storage', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        const service = create();

        expect(() => service.record('/flows/my')).not.toThrow();
        expect(service.url()).toBe('/flows/my');
        expect(() => service.clear()).not.toThrow();
    });
});
