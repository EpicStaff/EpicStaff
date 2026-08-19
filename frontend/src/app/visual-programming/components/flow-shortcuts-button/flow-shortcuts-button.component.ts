import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';

function isMacPlatform(): boolean {
    if (typeof navigator === 'undefined') return false;

    const navWithData = navigator as Navigator & { userAgentData?: { platform?: string } };
    const platform =
        (navWithData.userAgentData?.platform as string | undefined) ?? navigator.platform ?? navigator.userAgent;

    return /Mac|iPhone|iPad|iPod/i.test(platform);
}

@Component({
    selector: 'app-flow-shortcuts-button',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, MatTooltipModule],
    templateUrl: './flow-shortcuts-button.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./flow-shortcuts-button.component.scss'],
})
export class FlowShortcutsButtonComponent {
    label = input<string>(`${isMacPlatform() ? 'Cmd' : 'Ctrl'} + /`);
    icon = input<string>('shortcut');
    iconSize = input<string>('12px');
    textEnd = input<boolean>(false);
    active = input<boolean>(false);

    clicked = output<void>();
}
