import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
} from '@angular/core';
import { NgFor, NgStyle, NgSwitch, NgSwitchCase } from '@angular/common';
import { NodeType } from '../../core/enums/node-type';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu/flow-graph-core-menu.component';
import { FlowProjectsContextMenuComponent } from './section-projects/section-projects.component';
import { LlmMenuComponent } from './llm-menu/llm-menu.component';
import { ToolsMenuComponent } from './tools-menu/tools-menu.component';
import { StaffMenuComponent } from './staff-menu/staff-menu.component';
import { ProjectGraphCoreMenuComponent } from './project-graph-core-menu/project-graph-core-menu';

export type MenuType =
  | 'flow-core'
  | 'project-core'
  | 'projects'
  | 'llms'
  | 'tools'
  | 'staff';

export type MenuContext = 'flow-graph' | 'project-graph';

@Component({
  selector: 'app-flow-graph-context-menu',
  standalone: true,
  templateUrl: './flow-graph-context-menu.component.html',
  styleUrls: ['./flow-graph-context-menu.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgSwitch,
    NgSwitchCase,
    NgFor,
    NgStyle,
    FlowGraphCoreMenuComponent,
    FlowProjectsContextMenuComponent,
    LlmMenuComponent,
    ToolsMenuComponent,
    StaffMenuComponent,
    ProjectGraphCoreMenuComponent,
  ],
})
export class FlowGraphContextMenuComponent {
  @Input({ required: true })
  public position: { x: number; y: number } = { x: 0, y: 0 };

  private _menuContext: MenuContext = 'flow-graph';
  @Input()
  set menuContext(value: MenuContext) {
    this._menuContext = value;
    this.selectedMenu = value === 'flow-graph' ? 'flow-core' : 'project-core';
  }
  get menuContext(): MenuContext {
    return this._menuContext;
  }
  public get topPosition(): number {
    return this.menuContext === 'flow-graph'
      ? this.position.y - 80
      : this.position.y - 130;
  }

  public get leftPosition(): number {
    return this.menuContext === 'flow-graph'
      ? this.position.x - 70
      : this.position.x - 70;
  }
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType;
    data?: any;
  }>();

  public searchTerm: string = '';

  public selectedMenu: MenuType =
    this.menuContext === 'flow-graph' ? 'flow-core' : 'project-core';

  public get menuItems(): { label: string; type: MenuType }[] {
    if (this.menuContext === 'flow-graph') {
      return [
        { label: 'Core', type: 'flow-core' },
        { label: 'Projects', type: 'projects' },
        // { label: 'Models', type: 'llms' },
      ];
    } else {
      return [
        { label: 'Core', type: 'project-core' },
        { label: 'Staff', type: 'staff' },
        { label: 'Tools', type: 'tools' },
        { label: 'Models', type: 'llms' },
      ];
    }
  }

  public get menuWidth(): string {
    if (
      this.selectedMenu === 'flow-core' ||
      this.selectedMenu === 'project-core'
    ) {
      return 'auto';
    }
    return '380px';
  }

  public onSelectMenu(type: MenuType): void {
    this.selectedMenu = type;
  }

  public onSearchInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.searchTerm = input.value;
  }

  public onNodeSelected(event: { type: NodeType; data: any }): void {
    console.log('Node selected:', event.data);
    this.nodeSelected.emit(event);
  }
}
