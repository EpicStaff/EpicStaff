import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

function isMacPlatform(): boolean {
    if (typeof navigator === 'undefined') return false;

    const navWithData = navigator as Navigator & { userAgentData?: { platform?: string } };
    const platform =
        (navWithData.userAgentData?.platform as string | undefined) ?? navigator.platform ?? navigator.userAgent;

    return /Mac|iPhone|iPad|iPod/i.test(platform);
}

@Component({
    selector: 'app-flow-shortcuts-button',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './flow-shortcuts-button.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./flow-shortcuts-button.component.scss'],
})
export class FlowShortcutsButtonComponent {
    label = input<string>(`${isMacPlatform() ? 'Cmd' : 'Ctrl'} + /`);
    icon = input<string>('shortcut');
    iconSize = input<string>('12px');
    /** Moves the icon vertically, for icons whose drawing sits off-centre in their box. */
    iconOffsetY = input<string>('0px');
    textEnd = input<boolean>(false);
    active = input<boolean>(false);
    /** The button's name for screen readers when its label is a symbol. */
    ariaLabel = input<string | null>(null);

    clicked = output<void>();
}
