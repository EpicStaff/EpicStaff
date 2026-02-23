import { Component, output, input } from '@angular/core';
import { AppIconComponent } from 'src/app/shared/components/app-icon/app-icon.component';
import { CommonModule } from '@angular/common';

function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false;

  const navAny = navigator as any;
  const platform =
    (navAny.userAgentData?.platform as string | undefined) ??
    (navigator.platform ?? navigator.userAgent);

  return /Mac|iPhone|iPad|iPod/i.test(platform);
}

@Component({
  selector: 'app-flow-shortcuts-button',
  standalone: true,
  imports: [CommonModule, AppIconComponent],
  templateUrl: './flow-shortcuts-button.component.html',
  styleUrls: ['./flow-shortcuts-button.component.scss'],
})
export class FlowShortcutsButtonComponent {
  label = input<string>(`${isMacPlatform() ? 'Cmd' : 'Ctrl'} + /`);
  icon = input<string>('ui/shortcut');
  iconSize = input<string>('12');

  clicked = output<void>();
}