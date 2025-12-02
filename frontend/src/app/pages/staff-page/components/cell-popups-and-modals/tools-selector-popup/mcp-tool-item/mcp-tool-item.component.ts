import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { NgClass } from '@angular/common';
import { GetMcpToolRequest } from '../../../../../../features/tools/models/mcp-tool.model';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-mcp-tool-item',
  standalone: true,
  imports: [NgClass, MatIconModule],
  template: `
    <div
      class="mcp-tool-item"
      [ngClass]="{ 'selected-tool': isSelected }"
      (click)="onToolToggle()"
    >
      <mat-icon>hub</mat-icon>
      <span class="tool-name">
        {{ tool.name }}
      </span>
      <span class="tool-description">
        {{ tool.tool_name }}
      </span>
      <input
        type="checkbox"
        [checked]="isSelected"
        (click)="onCheckboxClick($event)"
      />
    </div>
  `,
  styleUrls: ['./mcp-tool-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class McpToolItemComponent {
  @Input() public tool!: GetMcpToolRequest;
  @Input() public isSelected: boolean = false;

  @Output() public toolToggled = new EventEmitter<GetMcpToolRequest>();

  public onToolToggle(): void {
    this.toolToggled.emit(this.tool);
  }

  public onCheckboxClick(event: Event): void {
    event.stopPropagation();
    this.toolToggled.emit(this.tool);
  }
}

