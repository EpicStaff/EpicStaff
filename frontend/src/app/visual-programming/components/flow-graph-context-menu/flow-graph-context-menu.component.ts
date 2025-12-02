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
import { NgStyle } from '@angular/common';
import { NodeType } from '../../core/enums/node-type';
import { MenuType } from '../../core/enums/menu-type.enum';
import { FlowGraphCoreContextMenuComponent } from './flow-graph-core-context-menu/flow-graph-core-context-menu.component';
import { TemplatesContextMenuComponent } from './templates-context-menu/templates-context-menu.component';
import { LlmMenuComponent } from './llm-menu/llm-menu.component';

@Component({
  selector: 'app-flow-graph-context-menu',
  standalone: true,
  templateUrl: './flow-graph-context-menu.component.html',
  styleUrls: ['./flow-graph-context-menu.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgStyle,
    FlowGraphCoreContextMenuComponent,
    TemplatesContextMenuComponent,
    LlmMenuComponent,
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

  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType;
    data?: any;
  }>();

  @Output() public createNewProject = new EventEmitter<void>();

  public readonly MenuType = MenuType;

  public get topPosition(): number {
    return this.position.y - 80;
  }

  public get leftPosition(): number {
    return this.position.x - 70;
  }

  public searchTerm: string = '';

  public selectedMenu: MenuType = MenuType.FlowCore;

  public get menuItems(): { label: string; type: MenuType }[] {
    return [
      { label: 'Core', type: MenuType.FlowCore },
      { label: 'Templates', type: MenuType.Templates },
      // { label: 'Models', type: MenuType.Llms },
    ];
  }

  public get menuWidth(): string {
    if (this.selectedMenu === MenuType.FlowCore) {
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

  public onCreateNewProject(): void {
    this.createNewProject.emit();
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
    const desiredTop = this.position.y - 80;
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
