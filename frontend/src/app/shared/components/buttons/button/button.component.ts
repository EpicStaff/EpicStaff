import {Component, input, Input} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';

@Component({
  selector: 'app-button',
  standalone: true,
  imports: [CommonModule, AppSvgIconComponent],
  templateUrl: './button.component.html',
  styleUrls: ['./button.component.scss'],
})
export class ButtonComponent {
  @Input() type: 'primary' | 'secondary' | 'ghost' | 'icon' | 'outline-primary' | 'outline-secondary' = 'primary';
  @Input() mod: 'default' | 'small' = 'default';
  @Input() leftIcon?: string; // e.g., 'x'
  @Input() leftIconColor?: string;
  @Input() rightIcon?: string; // e.g., 'chevron-down'
  @Input() rightIconColor?: string;
  @Input() ariaLabel?: string; // For accessibility
  disabled = input<boolean>(false);
}
