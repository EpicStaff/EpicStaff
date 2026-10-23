import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';

import { PluginLoginAutoContinueService } from './plugin-login-auto-continue.service';

describe('PluginLoginAutoContinueService', () => {
    afterEach(() => sessionStorage.clear());

    function service(document?: unknown): PluginLoginAutoContinueService {
        TestBed.configureTestingModule({
            providers: document === undefined ? [] : [{ provide: DOCUMENT, useValue: document }],
        });
        return TestBed.inject(PluginLoginAutoContinueService);
    }

    it('lets a sign-in continue by itself once, and every new sign-in once', () => {
        const autoContinue = service();

        expect(autoContinue.claim('state-1')).toBe(true);
        expect(autoContinue.claim('state-1')).toBe(false);
        expect(autoContinue.claim('state-2')).toBe(true);
        expect(sessionStorage.getItem('epicstaff.pluginLogin.autoContinuedState')).toBe('state-2');
    });

    it('never continues by itself when storage is blocked', () => {
        const blocked = {
            defaultView: {
                get sessionStorage(): Storage {
                    throw new DOMException('Blocked', 'SecurityError');
                },
            },
        };

        expect(service(blocked).claim('state-1')).toBe(false);
    });
});
