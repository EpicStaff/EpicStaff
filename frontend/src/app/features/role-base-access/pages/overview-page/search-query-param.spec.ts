import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Type } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { ConfigService } from '../../../../services/config';
import { ApiKeysTabComponent } from './api-keys-tab/api-keys-tab.component';
import { OrganizationsTabComponent } from './organizations-tab/organizations-tab.component';
import { RolesTabComponent } from './roles-tab/roles-tab.component';
import { UsersTabComponent } from './users-tab/users-tab.component';

// jsdom has no ResizeObserver; table and button directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

// A link to one member, role, API key or organization lands on its tab with the search box filled in.
describe.each<[string, Type<unknown>]>([
    ['users', UsersTabComponent],
    ['roles', RolesTabComponent],
    ['api-keys', ApiKeysTabComponent],
    ['organizations', OrganizationsTabComponent],
])('/workspace/%s ?search=', (path, component) => {
    async function searchBoxAt(url: string): Promise<string> {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([{ path: `workspace/${path}`, component }], withComponentInputBinding()),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(url);
        return harness.routeNativeElement!.querySelector<HTMLInputElement>('.search__input')!.value;
    }

    it('fills the search box with the text', async () => {
        expect(await searchBoxAt(`/workspace/${path}?search=ada@example.com`)).toBe('ada@example.com');
    });

    it('leaves the search box empty without it', async () => {
        expect(await searchBoxAt(`/workspace/${path}`)).toBe('');
    });
});
