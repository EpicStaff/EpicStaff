import { Component, HostListener } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { EpicChatService } from '../../features/epic-chat/epic-chat.service';
import { LeftSidebarComponent } from './sidenav/sidenav.component';

@Component({
    selector: 'app-main-layout',
    standalone: true,
    imports: [LeftSidebarComponent, RouterOutlet],
    styles: [
        `
            :host {
                display: flex;
                height: 100%;
                width: 100%;
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

                overflow-y: auto;
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
export class MainLayoutComponent {
    private isDockResizing = false;
    private dockResizeStartX = 0;
    private dockResizeStartWidth = 0;

    constructor(public epicChatService: EpicChatService) {}

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
