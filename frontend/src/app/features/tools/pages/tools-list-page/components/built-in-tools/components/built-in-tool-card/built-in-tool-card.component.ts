import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { Tool } from '../../../../../../models/tool.model';
import { CommonModule } from '@angular/common';
import { AppIconComponent } from '../../../../../../../../shared/components/app-icon/app-icon.component';
import { TOOL_CATEGORIES_CONFIG } from '../../../../../../constants/built-in-tools-categories';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { TOOL_PROVIDERS_AND_DESCRIPTIONS } from '../../../../../../constants/tool-providers-and-descriptions';

@Component({
  selector: 'app-built-in-tool-card',
  standalone: true,
  imports: [
    CommonModule,
    AppIconComponent,
    ToggleSwitchComponent,
    ButtonComponent,
  ],
  templateUrl: './built-in-tool-card.component.html',
  styleUrls: ['./built-in-tool-card.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BuiltInToolCardComponent {
  @Input() public tool!: Tool;
  @Input() public starred: boolean = false;
  @Output() public configure = new EventEmitter<Tool>();
  @Output() public enabledChange = new EventEmitter<{
    tool: Tool;
    enabled: boolean;
  }>();

  constructor(private cdr: ChangeDetectorRef) {}

  public getCategoryConfig(): {
    name: string;
    icon: string;
    toolIds: number[];
  } {
    return (
      TOOL_CATEGORIES_CONFIG.find((cat) =>
        cat.toolIds.includes(this.tool.id)
      ) || TOOL_CATEGORIES_CONFIG.find((cat) => cat.name === 'Other')!
    );
  }

  public getCategory(): string {
    return this.getCategoryConfig().name;
  }

  public getIconName(): string {
    return this.getCategoryConfig().icon;
  }

  public get provider(): string {
    return TOOL_PROVIDERS_AND_DESCRIPTIONS[this.tool.id]?.provider || '';
  }

  public get toolDescription(): string {
    return TOOL_PROVIDERS_AND_DESCRIPTIONS[this.tool.id]?.description || '';
  }

  public get starIcon(): string {
    return this.starred ? 'ui/star-filled' : 'ui/star';
  }

  public onConfigure(): void {
    console.log('Configure clicked for tool:', this.tool);
    this.configure.emit(this.tool);
  }

  public onToggle(enabled: boolean): void {
    console.log('Toggle clicked for tool:', this.tool, 'new state:', enabled);
    this.enabledChange.emit({ tool: this.tool, enabled });
  }

  public onStar(): void {
    console.log('Star clicked for tool:', this.tool);
    this.starred = !this.starred;
    this.cdr.markForCheck();
  }
}
