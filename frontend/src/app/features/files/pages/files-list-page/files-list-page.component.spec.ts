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

function headerSearch(harness: RouterTestingHarness): HTMLInputElement | null | undefined {
    return harness.routeNativeElement?.querySelector<HTMLInputElement>('.search-input');
}

describe('FilesListPageComponent header search', () => {
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

    it('is gone on Persistent Data, which searches keys in its own grid, and back on another tab', async () => {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/files/persistent-data');
        expect(headerSearch(harness)).toBeNull();

        await harness.navigateByUrl('/files/storage');
        expect(headerSearch(harness)?.placeholder).toBe('Search collections, folders, files...');
    });

    it('clears the search term when the Files tab changes, not within the same tab', async () => {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/files/storage');
        const search = harness.routeDebugElement!.injector.get(FilesSearchService);

        search.setSearchTerm('report');
        await harness.navigateByUrl('/files/storage?page=2');
        expect(search.searchTerm()).toBe('report');

        await harness.navigateByUrl('/files/persistent-data');
        expect(search.searchTerm()).toBe('');
    });
});

describe('FilesListPageComponent header create button', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('has no top-right Create table button on Persistent Data, even with every permission', async () => {
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
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        const harness = await RouterTestingHarness.create();
        const headerButton = () => harness.routeNativeElement?.querySelector('.header-actions app-button');

        // Positive control: the same permissions do render the header button on another tab.
        await harness.navigateByUrl('/files/storage');
        expect(headerButton()?.textContent?.trim()).toBe('Add files');

        await harness.navigateByUrl('/files/persistent-data');
        expect(headerButton()).toBeNull();
    });
});
