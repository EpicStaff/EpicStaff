import {
    afterNextRender,
    booleanAttribute,
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    Injector,
    input,
    viewChild,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { RouteTab } from './route-tabs.interface';

@Component({
    selector: 'app-route-tabs',
    templateUrl: './route-tabs.component.html',
    styleUrls: ['./route-tabs.component.scss'],
    imports: [RouterLink, RouterLinkActive, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: { '[class.route-tabs--scrollable]': 'scrollable()' },
})
export class RouteTabsComponent {
    readonly tabs = input.required<RouteTab[]>();
    /**
     * Tabs that do not fit scroll sideways instead of wrapping their labels: one line each, a thin scrollbar under
     * them, the active tab scrolled into view. For a page whose tabs outgrow narrow widths (Settings).
     */
    readonly scrollable = input(false, { transform: booleanAttribute });

    private readonly strip = viewChild.required<ElementRef<HTMLElement>>('strip');

    readonly visibleTabs = computed(() => this.tabs().filter((tab) => tab.isPermitted()));

    private readonly injector = inject(Injector);

    /** On load and on each navigation: the tab that became active is brought into view. */
    protected onActiveChange(isActive: boolean, tab: HTMLElement): void {
        if (!isActive || !this.scrollable()) return;
        afterNextRender(() => this.scrollIntoView(tab), { injector: this.injector });
    }

    /** A vertical wheel (a mouse without a sideways one) scrolls the strip while it has room to; then the page. */
    protected onWheel(event: WheelEvent): void {
        if (!this.scrollable() || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
        const strip = this.strip().nativeElement;
        const canScroll =
            event.deltaY < 0 ? strip.scrollLeft > 0 : strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 1;
        if (!canScroll) return;
        strip.scrollLeft += event.deltaY;
        event.preventDefault();
    }

    /** Sideways only, unlike `Element.scrollIntoView`, which may scroll the page too. */
    private scrollIntoView(tab: HTMLElement): void {
        const strip = this.strip().nativeElement;
        const start = tab.offsetLeft;
        const end = start + tab.offsetWidth;
        if (start < strip.scrollLeft) {
            strip.scrollLeft = start;
        } else if (end > strip.scrollLeft + strip.clientWidth) {
            strip.scrollLeft = end - strip.clientWidth;
        }
    }
}
