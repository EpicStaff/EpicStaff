import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { RouteTabsComponent } from './route-tabs.component';
import { RouteTab } from './route-tabs.interface';

function renderTabs(tabs: RouteTab[]): HTMLAnchorElement[] {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
    const fixture = TestBed.createComponent(RouteTabsComponent);
    fixture.componentRef.setInput('tabs', tabs);
    fixture.detectChanges();
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('a.route-tab'));
}

describe('RouteTabsComponent', () => {
    it('marks a tab with its tour anchor, and only that tab', () => {
        const [anchoredTab, plainTab] = renderTabs([
            { routerLink: 'quickstart', label: 'Quickstart', tourAnchor: 'quickstart-tab', isPermitted: () => true },
            { routerLink: 'secrets', label: 'Secrets', isPermitted: () => true },
        ]);

        expect(anchoredTab.getAttribute('data-tour')).toBe('quickstart-tab');
        expect(plainTab.hasAttribute('data-tour')).toBe(false);
    });
});
