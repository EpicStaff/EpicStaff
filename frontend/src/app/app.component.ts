import { ChangeDetectionStrategy, Component, inject, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastComponent } from './services/notifications/notification/toast.component';
import { DefaultsService } from './shared/services/defaults/defaults.service';

@Component({
    selector: 'app-root',
    standalone: true,
    imports: [RouterOutlet, ToastComponent],
    template: `
        <router-outlet></router-outlet>
        <app-toast position="bottom-right"></app-toast>
        <app-toast position="top-center"></app-toast>
        <app-toast position="top-right"></app-toast>
    `,
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent implements OnInit {
    private defaultsService = inject(DefaultsService);

    ngOnInit(): void {
        this.defaultsService.load().subscribe({ error: () => void 0 });
    }
}
