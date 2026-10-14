import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs/operators';

import { LastVisitedTabService } from '../../services/last-visited-tab.service';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

const TABBED_ROUTES: Record<string, string[]> = {
    '/tools': ['/tools/custom', '/tools/mcp'],
    '/flows': ['/flows/my', '/flows/templates'],
    '/storage': ['/storage/knowledge-sources', '/storage/files', '/storage/key-value-tables'],
};

@Component({
    selector: 'app-main-layout',
    imports: [LeftSidebarComponent, RouterOutlet],
    styles: [
        `
            :host {
                display: flex;
                flex: 1;
                width: 100%;
                min-height: 0;
                max-height: 100vh;
            }

            .sidebar-wrapper {
                width: 3.7rem;
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
        <div class="sidebar-wrapper">
            <app-left-sidebar></app-left-sidebar>
        </div>

        <div class="main-content">
            <router-outlet></router-outlet>
        </div>
    `,
})
export class MainLayoutComponent implements OnInit {
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
}
