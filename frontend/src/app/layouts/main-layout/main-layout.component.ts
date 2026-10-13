import { ChangeDetectionStrategy, Component, DestroyRef, HostListener, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';
import { filter } from 'rxjs/operators';

import { EpicChatService } from '../../features/epic-chat/epic-chat.service';
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

            .chat-dock-spacer {
                position: relative;
                flex-shrink: 0;
                border-right: 1px solid var(--color-divider-subtle);
                background: var(--color-background-body);
            }

            .chat-dock-resizer {
                position: absolute;
                top: 0;
                right: -4px;
                width: 8px;
                height: 100%;
                cursor: col-resize;
                z-index: 10;
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

        @if (epicChatService.isDocked() && epicChatService.isChatOpen()) {
            <div
                class="chat-dock-spacer"
                [style.width.px]="epicChatService.dockWidth()"
            >
                <div
                    class="chat-dock-resizer"
                    (mousedown)="onDockResizeStart($event)"
                ></div>
            </div>
        }

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

    private isDockResizing = false;
    private dockResizeStartX = 0;
    private dockResizeStartWidth = 0;

    private router = inject(Router);
    private destroyRef = inject(DestroyRef);
    private lastVisitedTabService = inject(LastVisitedTabService);

    constructor(public epicChatService: EpicChatService) {}

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

    public onDockResizeStart(event: MouseEvent): void {
        if (!this.epicChatService.isDocked()) {
            return;
        }
        event.preventDefault();
        this.isDockResizing = true;
        this.dockResizeStartX = event.clientX;
        this.dockResizeStartWidth = this.epicChatService.dockWidth();
    }

    @HostListener('window:mousemove', ['$event'])
    public onDockResizeMove(event: MouseEvent): void {
        if (!this.isDockResizing) {
            return;
        }
        const delta = event.clientX - this.dockResizeStartX;
        this.epicChatService.setDockWidth(this.dockResizeStartWidth + delta);
    }

    @HostListener('window:mouseup')
    public onDockResizeEnd(): void {
        this.isDockResizing = false;
    }
}
