import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
    selector: 'app-routed-auth-shell',
    imports: [RouterOutlet],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: '<router-outlet></router-outlet>',
    styles: [
        `
            :host {
                display: flex;
                flex-direction: column;
                min-height: 100dvh;
                width: 100%;
            }
        `,
    ],
})
export class RoutedAuthShellComponent {}
