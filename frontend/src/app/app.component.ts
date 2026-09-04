import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { NavigationStart, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

import { ToastComponent } from './services/notifications/notification/toast.component';

@Component({
    selector: 'app-root',
    imports: [RouterOutlet, ToastComponent],
    template: `
        <router-outlet></router-outlet>
        <app-toast position="bottom-right"></app-toast>
        <app-toast position="top-right"></app-toast>
    `,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
    constructor(
        private router: Router,
        private cdkDialog: Dialog
    ) {
        this.router.events.pipe(filter((e) => e instanceof NavigationStart)).subscribe(() => {
            this.cdkDialog.closeAll();
        });
    }
}
