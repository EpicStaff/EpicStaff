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

    function renderScrollable(scrollable: boolean): HTMLElement {
        TestBed.configureTestingModule({ providers: [provideRouter([])] });
        const fixture = TestBed.createComponent(RouteTabsComponent);
        fixture.componentRef.setInput('tabs', [{ routerLink: 'secrets', label: 'Secrets', isPermitted: () => true }]);
        fixture.componentRef.setInput('scrollable', scrollable);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it.each([false, true])('takes the scrollable look only when asked (scrollable: %s)', (scrollable) => {
        expect(renderScrollable(scrollable).classList.contains('route-tabs--scrollable')).toBe(scrollable);
    });

    it('scrolls the strip sideways with a vertical wheel while it has room to, then leaves the wheel to the page', () => {
        const strip = renderScrollable(true).querySelector<HTMLElement>('.tabs-wrapper')!;
        Object.defineProperty(strip, 'clientWidth', { value: 100 });
        Object.defineProperty(strip, 'scrollWidth', { value: 300 });

        const towardsEnd = new WheelEvent('wheel', { deltaY: 50, cancelable: true });
        strip.dispatchEvent(towardsEnd);
        expect(strip.scrollLeft).toBe(50);
        expect(towardsEnd.defaultPrevented).toBe(true);

        strip.scrollLeft = 0;
        const towardsStart = new WheelEvent('wheel', { deltaY: -50, cancelable: true });
        strip.dispatchEvent(towardsStart);
        expect(towardsStart.defaultPrevented).toBe(false);
    });

    it('turns a wheel reported in lines (Firefox) into pixels', () => {
        const strip = renderScrollable(true).querySelector<HTMLElement>('.tabs-wrapper')!;
        Object.defineProperty(strip, 'clientWidth', { value: 100 });
        Object.defineProperty(strip, 'scrollWidth', { value: 300 });

        strip.dispatchEvent(
            new WheelEvent('wheel', { deltaY: 3, deltaMode: WheelEvent.DOM_DELTA_LINE, cancelable: true })
        );

        expect(strip.scrollLeft).toBe(48);
    });
});
