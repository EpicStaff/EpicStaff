import { Component, DestroyRef, HostListener, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs/operators';

import { EpicChatService } from '../../features/epic-chat/epic-chat.service';
import { LastVisitedTabService } from '../../services/last-visited-tab.service';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

const TABBED_ROUTES: Record<string, string[]> = {
    '/projects': ['/projects/my', '/projects/templates'],
    '/tools': ['/tools/custom', '/tools/mcp'],
    '/flows': ['/flows/my', '/flows/templates'],
    '/files': ['/files/knowledge-sources', '/files/storage'],
};

@Component({
    selector: 'app-main-layout',
    standalone: true,
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
    template: `
        <div class="sidebar-wrapper">
            <app-left-sidebar></app-left-sidebar>
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
