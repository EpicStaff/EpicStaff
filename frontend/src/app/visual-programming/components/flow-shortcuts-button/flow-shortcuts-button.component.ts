import { Component, output, input } from '@angular/core';
import { AppIconComponent } from 'src/app/shared/components/app-icon/app-icon.component';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-flow-shortcuts-button',
  standalone: true,
  imports: [CommonModule, AppIconComponent],
  templateUrl: './flow-shortcuts-button.component.html',
  styleUrls: ['./flow-shortcuts-button.component.scss'],
})
export class FlowShortcutsButtonComponent {
  label = input<string>('Ctrl + /');
  icon = input<string>('ui/shortcut');
  iconSize = input<string>('12');

  clicked = output<void>();
}