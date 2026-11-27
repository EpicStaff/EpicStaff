import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, RouterOutlet } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { SideSectionNavComponent } from './side-section-nav.component';
import { SideSectionNavItem } from './side-section-nav.interface';

// jsdom has no ResizeObserver; the overflow tooltip only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const ITEMS: SideSectionNavItem[] = [
    { route: 'general', label: 'General', icon: 'ti-settings' },
    { route: 'shortcuts', label: 'Shortcuts', icon: 'ti-keyboard' },
];

@Component({
    template: `<app-side-section-nav [items]="items" /><router-outlet />`,
    imports: [SideSectionNavComponent, RouterOutlet],
})
class HostComponent {
    protected readonly items = ITEMS;
}

@Component({ template: '' })
class SectionComponent {}

describe('SideSectionNavComponent', () => {
    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        path: 'settings',
                        component: HostComponent,
                        children: [
                            { path: 'general', component: SectionComponent },
                            { path: 'shortcuts', component: SectionComponent },
                        ],
                    },
                ]),
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    function rows(harness: RouterTestingHarness): HTMLAnchorElement[] {
        return Array.from((harness.routeNativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('a.row'));
    }

    function selected(harness: RouterTestingHarness): string[] {
        return rows(harness)
            .filter((row) => row.classList.contains('row--selected') && row.getAttribute('aria-current') === 'page')
            .map((row) => row.textContent!.trim());
    }

    it('links each section to its route and marks the active one', async () => {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/settings/shortcuts');

        expect(rows(harness).map((row) => row.getAttribute('href'))).toEqual([
            '/settings/general',
            '/settings/shortcuts',
        ]);
        expect(selected(harness)).toEqual(['Shortcuts']);

        rows(harness)[0].click();
        await harness.fixture.whenStable();
        harness.detectChanges();

        expect(selected(harness)).toEqual(['General']);
    });
});
