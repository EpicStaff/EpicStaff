import { Dialog } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { ChangeDetectionStrategy, Component, OnInit } from '@angular/core';
import { NavigationStart, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { ToastComponent } from './services/notifications/notification/toast.component';
import { ToastPosition } from './services/notifications/toast.service';

@Component({
    selector: 'app-root',
    imports: [RouterOutlet],
    template: `<router-outlet></router-outlet>`,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent implements OnInit {
    private toastWrappers: HTMLElement[] = [];

    constructor(
        private router: Router,
        private cdkDialog: Dialog,
        private overlay: Overlay
    ) {
        this.router.events.pipe(filter((e) => e instanceof NavigationStart)).subscribe(() => {
            this.cdkDialog.closeAll();
        });
    }

    ngOnInit(): void {
        this.attachToastOverlay('bottom-right');
        this.attachToastOverlay('top-right');
        this.observeOverlayContainer();
    }

    private attachToastOverlay(position: ToastPosition): void {
        const positionStrategy = this.overlay.position().global().right('20px');
        if (position === 'top-right') {
            positionStrategy.top('20px');
        } else {
            positionStrategy.bottom('20px');
        }

        const overlayRef = this.overlay.create({
            positionStrategy,
            panelClass: 'toast-overlay-panel',
            hasBackdrop: false,
        });

        const componentRef = overlayRef.attach(new ComponentPortal(ToastComponent));
        componentRef.setInput('position', position);

        const wrapper = overlayRef.hostElement?.closest('[popover]') as HTMLElement | null;
        if (wrapper) {
            this.toastWrappers.push(wrapper);
        }
    }

    private observeOverlayContainer(): void {
        const container = document.querySelector('.cdk-overlay-container');
        if (!container) return;

        const observer = new MutationObserver(() => {
            for (const wrapper of this.toastWrappers) {
                try {
                    wrapper.hidePopover();
                    wrapper.showPopover();
                } catch {
                    // Popover not in a togglable state; skip.
                }
            }
        });

        observer.observe(container, { childList: true });
    }
}
