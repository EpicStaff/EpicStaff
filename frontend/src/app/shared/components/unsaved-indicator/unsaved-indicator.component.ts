import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output, } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Spinner2Component } from '../spinner-type2/spinner.component';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

@Component({
  selector: 'app-unsaved-indicator',
  imports: [ CommonModule, AppSvgIconComponent ],
  templateUrl: './unsaved-indicator.component.html',
  styleUrl: './unsaved-indicator.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class UnsavedIndicatorComponent {
  @Input() show = false;
}
