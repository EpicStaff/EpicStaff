import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { RouteTab } from './route-tabs.interface';

@Component({
    selector: 'app-route-tabs',
    templateUrl: './route-tabs.component.html',
    styleUrls: ['./route-tabs.component.scss'],
    imports: [RouterLink, RouterLinkActive, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RouteTabsComponent {
    readonly tabs = input.required<RouteTab[]>();

    readonly visibleTabs = computed(() => this.tabs().filter((tab) => tab.isPermitted()));
}
