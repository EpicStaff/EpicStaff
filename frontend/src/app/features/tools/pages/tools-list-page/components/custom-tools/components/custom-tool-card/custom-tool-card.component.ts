import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { GetPythonCodeToolRequest } from '../../../../../../models/python-code-tool.model';
import { AppIconComponent } from '../../../../../../../../shared/components/app-icon/app-icon.component';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';

@Component({
  selector: 'app-custom-tool-card',
  standalone: true,
  templateUrl: './custom-tool-card.component.html',
  styleUrls: ['./custom-tool-card.component.scss'],
  imports: [AppIconComponent, ToggleSwitchComponent, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CustomToolCardComponent {
  @Input() public tool!: GetPythonCodeToolRequest;
  @Input() public enabled: boolean = false;
  @Input() public starred: boolean = false;
  @Output() public configure = new EventEmitter<GetPythonCodeToolRequest>();
  @Output() public toggle = new EventEmitter<{
    tool: GetPythonCodeToolRequest;
    enabled: boolean;
  }>();
  @Output() public star = new EventEmitter<{
    tool: GetPythonCodeToolRequest;
    starred: boolean;
  }>();
  @Output() public delete = new EventEmitter<GetPythonCodeToolRequest>();

  constructor(private cdr: ChangeDetectorRef) {}

  public get starIcon(): string {
    return this.starred ? 'ui/star-filled' : 'ui/star';
  }

  public onConfigure(): void {
    console.log('Configure clicked for tool:', this.tool);
    this.configure.emit(this.tool);
  }

  public onToggle(val: boolean): void {
    console.log('Toggle clicked for tool:', this.tool);
    this.enabled = val;
    this.toggle.emit({ tool: this.tool, enabled: val });
  }

  public onStar(): void {
    console.log('Star clicked for tool:', this.tool);
    this.starred = !this.starred;
    this.cdr.markForCheck();
    this.star.emit({ tool: this.tool, starred: this.starred });
  }

  public onDelete(): void {
    console.log('Delete clicked for tool:', this.tool);
    this.delete.emit(this.tool);
  }
}
