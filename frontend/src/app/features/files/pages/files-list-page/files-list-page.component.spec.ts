import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FilesSearchService } from '../../services/files-search.service';
import { FilesListPageComponent } from './files-list-page.component';

// jsdom has no ResizeObserver; the overflow directives in the template only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({ template: '' })
class TabStubComponent {}

async function placeholderAt(url: string, harness?: RouterTestingHarness): Promise<string | undefined> {
    const activeHarness = harness ?? (await RouterTestingHarness.create());
    await activeHarness.navigateByUrl(url);
    return activeHarness.routeNativeElement?.querySelector<HTMLInputElement>('.search-input')?.placeholder;
}

describe('FilesListPageComponent header search placeholder', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        path: 'files',
                        component: FilesListPageComponent,
                        children: [
                            { path: 'storage', component: TabStubComponent },
                            { path: 'persistent-data', component: TabStubComponent },
                        ],
                    },
                ]),
                { provide: PermissionsService, useValue: { can: () => false } },
            ],
        });
    });

    it('reads "Search keys..." on Persistent Data and reverts on another tab', async () => {
        const harness = await RouterTestingHarness.create();
        expect(await placeholderAt('/files/persistent-data', harness)).toBe('Search keys...');
        expect(await placeholderAt('/files/storage', harness)).toBe('Search collections, folders, files...');
    });

    it('clears the search term when the Files tab changes, not within the same tab', async () => {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/files/persistent-data');
        const search = harness.routeDebugElement!.injector.get(FilesSearchService);

        search.setSearchTerm('profile');
        await harness.navigateByUrl('/files/persistent-data?page=2');
        expect(search.searchTerm()).toBe('profile');

        await harness.navigateByUrl('/files/storage');
        expect(search.searchTerm()).toBe('');
    });
});
