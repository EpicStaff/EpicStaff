import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  Output,
} from '@angular/core';
import { GetMcpToolRequest } from '../../../../../../models/mcp-tool.model';
import { AppIconComponent } from '../../../../../../../../shared/components/app-icon/app-icon.component';
import { ToggleSwitchComponent } from '../../../../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';
import { ButtonComponent } from '../../../../../../../../shared/components/buttons/button/button.component';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-mcp-tool-card',
  standalone: true,
  templateUrl: './mcp-tool-card.component.html',
  styleUrls: ['./mcp-tool-card.component.scss'],
  imports: [AppIconComponent, ToggleSwitchComponent, ButtonComponent, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolCardComponent {
  @Input() public tool!: GetMcpToolRequest;
  @Input() public enabled: boolean = false;
  @Input() public starred: boolean = false;
  @Output() public configure = new EventEmitter<GetMcpToolRequest>();
  @Output() public toggle = new EventEmitter<{
    tool: GetMcpToolRequest;
    enabled: boolean;
  }>();
  @Output() public star = new EventEmitter<{
    tool: GetMcpToolRequest;
    starred: boolean;
  }>();
  @Output() public delete = new EventEmitter<GetMcpToolRequest>();

  constructor(private cdr: ChangeDetectorRef) {}

  public get starIcon(): string {
    return this.starred ? 'ui/star-filled' : 'ui/star';
  }

  public onConfigure(): void {
    console.log('Configure clicked for MCP tool:', this.tool);
    this.configure.emit(this.tool);
  }

  public onToggle(val: boolean): void {
    console.log('Toggle clicked for MCP tool:', this.tool);
    this.enabled = val;
    this.toggle.emit({ tool: this.tool, enabled: val });
  }

  public onStar(): void {
    console.log('Star clicked for MCP tool:', this.tool);
    this.starred = !this.starred;
    this.cdr.markForCheck();
    this.star.emit({ tool: this.tool, starred: this.starred });
  }

  public onDelete(): void {
    console.log('Delete clicked for MCP tool:', this.tool);
    this.delete.emit(this.tool);
  }
}


