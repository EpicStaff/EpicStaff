import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';
import { filter } from 'rxjs/operators';

import { LastVisitedTabService } from '../../services/last-visited-tab.service';
import { MAIN_SIDENAV_WIDTH_KEY, MAIN_SIDENAV_WIDTH_OPTIONS } from './main-sidenav-width';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

const TABBED_ROUTES: Record<string, string[]> = {
    '/tools': ['/tools/custom', '/tools/mcp'],
    '/flows': ['/flows/my', '/flows/templates'],
    '/storage': ['/storage/knowledge-sources', '/storage/files', '/storage/key-value-tables'],
};

@Component({
    selector: 'app-main-layout',
    imports: [LeftSidebarComponent, RouterOutlet, ResizableSidebarDirective],
    styles: [
        `
            :host {
                display: flex;
                flex: 1;
                width: 100%;
                min-height: 0;
                max-height: 100vh;
            }

            /* Width follows the pointer while dragging, so it is never animated. */
            .sidebar-wrapper {
                position: relative;
                flex-shrink: 0;
            }

            /* The main-content area flexes to fill all remaining horizontal space. */
            .main-content {
                flex: 1;
                min-width: 0;
                overflow-y: auto;
                overflow-x: hidden;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.Eager,
    template: `
        <div
            #sidebarWrapper
            class="sidebar-wrapper"
            [style.width.px]="sidenavWidth()"
        >
            <app-left-sidebar
                [width]="sidenavWidth()"
                (expandedToggle)="toggleSidenav()"
            ></app-left-sidebar>
            <div
                class="resizable-sidebar-handle"
                [appResizableSidebar]="sidenavWidthKey"
                [sidebarTarget]="sidebarWrapper"
                [sidebarMinWidth]="sidenavWidthOptions.minWidth"
                [sidebarMaxWidth]="sidenavWidthOptions.maxWidth"
                [sidebarCollapse]="sidenavWidthOptions.collapse"
                sidebarAriaLabel="Resize navigation sidebar"
            ></div>
        </div>

        <div class="main-content">
            <router-outlet></router-outlet>
        </div>
    `,
})
export class MainLayoutComponent implements OnInit {
    // Declared ahead of the state because the sidenavWidth initializer below reads it.
    private readonly sidebarWidthService = inject(SidebarWidthService);

    /** Single source of truth for the sidebar state: collapsed and expanded are derived from it. */
    protected readonly sidenavWidth = this.sidebarWidthService.getWidth(
        MAIN_SIDENAV_WIDTH_KEY,
        MAIN_SIDENAV_WIDTH_OPTIONS
    );

    protected readonly sidenavWidthKey = MAIN_SIDENAV_WIDTH_KEY;
    protected readonly sidenavWidthOptions = MAIN_SIDENAV_WIDTH_OPTIONS;

    private router = inject(Router);
    private destroyRef = inject(DestroyRef);
    private lastVisitedTabService = inject(LastVisitedTabService);

    ngOnInit(): void {
        this.router.events
            .pipe(
                filter((e): e is NavigationEnd => e instanceof NavigationEnd),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((e) => {
                const url = e.urlAfterRedirects;
                for (const [parent, tabs] of Object.entries(TABBED_ROUTES)) {
                    if (tabs.includes(url)) {
                        this.lastVisitedTabService.set(parent, url);
                        break;
                    }
                }
            });
    }

    /** The sidenav's open/close control: the layout owns the width, so it applies and persists the change. */
    protected toggleSidenav(): void {
        this.sidebarWidthService.toggleCollapsed(MAIN_SIDENAV_WIDTH_KEY, MAIN_SIDENAV_WIDTH_OPTIONS);
    }
}
