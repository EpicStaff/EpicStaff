import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';

import { PluginLoginNavigationService } from './plugin-login-navigation.service';

describe('PluginLoginNavigationService', () => {
    const location = { origin: 'http://epicstaff.localhost', replace: vi.fn(), assign: vi.fn() };

    function service(): PluginLoginNavigationService {
        TestBed.configureTestingModule({ providers: [{ provide: DOCUMENT, useValue: { location } }] });
        return TestBed.inject(PluginLoginNavigationService);
    }

    beforeEach(() => vi.clearAllMocks());

    it('replaces the page with the path on its own origin, and never assigns', () => {
        service().continueTo('/api/auth/plugin-authorize/?plugin=weather&org=3');

        expect(location.replace).toHaveBeenCalledExactlyOnceWith(
            'http://epicstaff.localhost/api/auth/plugin-authorize/?plugin=weather&org=3'
        );
        expect(location.assign).not.toHaveBeenCalled();
    });

    it('goes nowhere when the path would leave the origin', () => {
        service().continueTo('//evil.example/api/auth/plugin-authorize/?plugin=weather');

        expect(location.replace).not.toHaveBeenCalled();
    });
});
