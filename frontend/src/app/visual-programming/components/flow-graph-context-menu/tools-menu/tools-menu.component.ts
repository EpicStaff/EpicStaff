import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ToolConfigService } from '../../../../services/tool_config.service';
import { ToolConfig } from '../../../../features/tools/models/tool_config.model';
import { NodeType } from '../../../core/enums/node-type';

@Component({
  selector: 'app-tools-menu',
  standalone: true,
  imports: [CommonModule],
  template: `
    <ul>
      <li
        *ngFor="let tool of filteredTools; trackBy: trackByToolId"
        (click)="onToolClicked(tool)"
      >
        <i class="ti ti-tools"></i>
        <span class="tool-name">
          {{ tool.name }}
          <span
            class="status-marker"
            [ngClass]="{
              completed: tool.is_completed,
              'not-completed': !tool.is_completed
            }"
          ></span>
        </span>
        <i class="ti ti-plus plus-icon"></i>
      </li>
    </ul>
  `,
  styles: [
    `
      ul {
        list-style: none;
        padding: 0 16px;
        margin: 0;
      }
      li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s ease;
        position: relative;
        gap: 16px;
        overflow: hidden;
      }
      li:hover {
        background: #2a2a2a;
      }
      li i {
        font-size: 18px;
        color: #9f6a00;
      }

      .tool-name {
        flex: 1;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      .status-marker {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;
      }
      .completed {
        background-color: green;
      }
      .not-completed {
        background-color: red;
      }
      .plus-icon {
        font-size: 18px;
        color: #bbb;
        opacity: 0;
        transition: opacity 0.2s ease, color 0.2s ease;
      }
      li:hover .plus-icon {
        opacity: 1;
        color: #fff;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsMenuComponent implements OnInit {
  @Input() public searchTerm: string = '';
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType.TOOL;
    data: ToolConfig;
  }>();

  public tools: ToolConfig[] = [];

  constructor(
    private toolConfigService: ToolConfigService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.toolConfigService.getToolConfigs().subscribe({
      next: (tools: ToolConfig[]) => {
        console.log('Tools:', tools);

        this.tools = tools;
        this.cdr.markForCheck();
      },
      error: (err) => console.error('Error fetching tool configs:', err),
    });
  }

  public get filteredTools(): ToolConfig[] {
    return this.tools.filter((tool) =>
      tool.name.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  public onToolClicked(tool: ToolConfig): void {
    this.nodeSelected.emit({ type: NodeType.TOOL, data: tool });
  }

  public trackByToolId(index: number, tool: ToolConfig): number {
    return tool.id;
  }
}
