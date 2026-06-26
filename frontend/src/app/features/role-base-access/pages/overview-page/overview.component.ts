import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';

import { HideInlineSubtitleOnOverflowDirective } from '../../../../shared/directives/hide-inline-subtitle-on-overflow.directive';

@Component({
    selector: 'app-overview',
    templateUrl: './overview.component.html',
    styleUrls: ['./overview.component.scss'],
    imports: [
        RouterOutlet,
        RouterLink,
        RouterLinkActive,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OverviewComponent {}
