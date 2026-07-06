import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { ThemeTokenDef } from '../../data/theme-tokens';

@Component({
    selector: 'app-token-preview',
    standalone: true,
    templateUrl: './token-preview.component.html',
    styleUrls: ['./token-preview.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TokenPreviewComponent {
    readonly token = input.required<ThemeTokenDef>();
}
