import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnDestroy,
  Output,
  ViewChild,
} from '@angular/core';
import { NgFor, NgStyle, NgSwitch, NgSwitchCase } from '@angular/common';
import { NodeType } from '../../core/enums/node-type';
import { FlowGraphCoreMenuComponent } from './flow-graph-core-menu/flow-graph-core-menu.component';
import { FlowProjectsContextMenuComponent } from './section-projects/section-projects.component';
import { LlmMenuComponent } from './llm-menu/llm-menu.component';
import { ToolsMenuComponent } from './tools-menu/tools-menu.component';
import { StaffMenuComponent } from './staff-menu/staff-menu.component';
import { ProjectGraphCoreMenuComponent } from './project-graph-core-menu/project-graph-core-menu';
import { FlowsMenuComponent } from './flows-menu/flows-menu.component';

export type MenuType =
  | 'flow-core'
  | 'project-core'
  | 'projects'
  | 'flows'
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
    FlowsMenuComponent,
    LlmMenuComponent,
    ToolsMenuComponent,
    StaffMenuComponent,
    ProjectGraphCoreMenuComponent,
  ],
})
export class FlowGraphContextMenuComponent
  implements AfterViewInit, OnDestroy
{
  private static readonly VIEWPORT_MARGIN = 16;
  private static readonly VIEWPORT_BOTTOM_MARGIN = 64;
  private static readonly OFFSCREEN_COORD = -10000;
  private positionValue: { x: number; y: number } = { x: 0, y: 0 };

  @Input({ required: true })
  set position(value: { x: number; y: number }) {
    this.positionValue = value;
    this.schedulePositionUpdate();
  }
  get position(): { x: number; y: number } {
    return this.positionValue;
  }

  @ViewChild('menuContainer')
  private menuContainer?: ElementRef<HTMLDivElement>;

  private topValue = 0;
  private leftValue = 0;
  public isMenuPositioned = false;
  private positionUpdateTimeoutId?: number;

  @Input() public currentFlowId: number | null = null;

  private _menuContext: MenuContext = 'flow-graph';
  @Input()
  set menuContext(value: MenuContext) {
    this._menuContext = value;
    this.selectedMenu = value === 'flow-graph' ? 'flow-core' : 'project-core';
    this.schedulePositionUpdate();
  }
  get menuContext(): MenuContext {
    return this._menuContext;
  }
  public get topPosition(): number {
    return this.isMenuPositioned
      ? this.topValue
      : FlowGraphContextMenuComponent.OFFSCREEN_COORD;
  }

  public get leftPosition(): number {
    return this.isMenuPositioned
      ? this.leftValue
      : FlowGraphContextMenuComponent.OFFSCREEN_COORD;
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
        { label: 'Flows', type: 'flows' },
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

  constructor(private readonly cdr: ChangeDetectorRef) {}

  public ngAfterViewInit(): void {
    this.schedulePositionUpdate();
  }

  public ngOnDestroy(): void {
    this.clearPendingPositionUpdate();
  }

  @HostListener('window:resize')
  public onWindowResize(): void {
    this.schedulePositionUpdate();
  }

  public onSelectMenu(type: MenuType): void {
    this.selectedMenu = type;
    this.schedulePositionUpdate();
  }

  public onSearchInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.searchTerm = input.value;
  }

  public onNodeSelected(event: { type: NodeType; data: any }): void {
    console.log('Node selected:', event.data);
    this.nodeSelected.emit(event);
  }

  private schedulePositionUpdate(): void {
    this.clearPendingPositionUpdate();
    this.isMenuPositioned = false;
    const timeoutFn = () => {
      this.positionUpdateTimeoutId = undefined;
      this.updatePositionWithinViewport();
    };
    this.positionUpdateTimeoutId =
      typeof window !== 'undefined'
        ? window.setTimeout(timeoutFn)
        : (setTimeout(timeoutFn) as unknown as number);
  }

  private clearPendingPositionUpdate(): void {
    if (this.positionUpdateTimeoutId !== undefined) {
      clearTimeout(this.positionUpdateTimeoutId);
      this.positionUpdateTimeoutId = undefined;
    }
  }

  private updatePositionWithinViewport(): void {
    const desiredTop =
      this.menuContext === 'flow-graph'
        ? this.position.y - 80
        : this.position.y - 130;
    const desiredLeft = this.position.x - 70;

    const viewportWidth =
      typeof window !== 'undefined' ? window.innerWidth : Number.MAX_SAFE_INTEGER;
    const viewportHeight =
      typeof window !== 'undefined'
        ? window.innerHeight
        : Number.MAX_SAFE_INTEGER;

    const { width: menuWidth, height: menuHeight } =
      this.getMenuDimensions();

    const maxLeft =
      viewportWidth - menuWidth - FlowGraphContextMenuComponent.VIEWPORT_MARGIN;
    const maxTop =
      viewportHeight -
      menuHeight -
      FlowGraphContextMenuComponent.VIEWPORT_BOTTOM_MARGIN;

    this.leftValue = this.clamp(
      desiredLeft,
      FlowGraphContextMenuComponent.VIEWPORT_MARGIN,
      Math.max(
        FlowGraphContextMenuComponent.VIEWPORT_MARGIN,
        maxLeft
      )
    );
    this.topValue = this.clamp(
      desiredTop,
      FlowGraphContextMenuComponent.VIEWPORT_MARGIN,
      Math.max(
        FlowGraphContextMenuComponent.VIEWPORT_MARGIN,
        maxTop
      )
    );

    this.isMenuPositioned = true;
    this.cdr.markForCheck();
  }

  private getMenuDimensions(): { width: number; height: number } {
    const fallback = { width: 360, height: 360 };
    if (!this.menuContainer?.nativeElement) {
      return fallback;
    }

    const rect = this.menuContainer.nativeElement.getBoundingClientRect();

    return {
      width: rect.width || fallback.width,
      height: rect.height || fallback.height,
    };
  }

  private clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
  }
}
