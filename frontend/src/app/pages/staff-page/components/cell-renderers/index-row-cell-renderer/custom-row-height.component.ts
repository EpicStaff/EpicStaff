import {
  Component,
  ElementRef,
  HostListener,
  NgZone,
  ChangeDetectorRef,
  ChangeDetectionStrategy,
  OnDestroy,
} from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-index-cell-renderer',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="row-index">{{ params?.value }}</span>
    <div class="resize-handler" [ngStyle]="{ opacity: resizerOpacity }"></div>
  `,
  styles: [
    `
      :host {
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        padding-bottom: 5px;
        position: relative;
        user-select: none;
      }
      .row-index {
        color: white;
        font-size: 14px;
        line-height: 1;
        cursor: pointer; /* Allow click on the index */
      }
      .resize-handler {
        position: absolute;
        bottom: 5px;
        width: 80%;
        height: 4px;
        background: rgba(200, 200, 200, 0.3);
        cursor: row-resize;
        transition: opacity 0.2s;
        border-radius: 2px;
        opacity: 0;
        touch-action: none;
      }
      :host:hover .resize-handler {
        opacity: 1;
      }
    `,
  ],
})
export class IndexCellRendererComponent
  implements ICellRendererAngularComp, OnDestroy
{
  params: any;
  isResizing = false;
  tempVisible = false;

  private startY = 0;
  private startHeight = 0;
  private animationFrame: number | null = null;
  private tempVisibleTimeout: any;

  constructor(
    private el: ElementRef,
    private zone: NgZone,
    private cd: ChangeDetectorRef
  ) {}

  agInit(params: any): void {
    this.params = params;
  }

  // Resizer opacity based on resizing or temporary visibility
  get resizerOpacity(): string {
    return this.isResizing || this.tempVisible ? '1' : '';
  }

  // Handle pointer down (initiates resizing)
  @HostListener('pointerdown', ['$event'])
  onPointerDown(event: PointerEvent) {
    const target = event.target as HTMLElement;
    if (target && target.classList.contains('resize-handler')) {
      this.isResizing = true;
      this.startY = event.clientY;
      this.startHeight = this.params.node.rowHeight || 60;
      target.setPointerCapture(event.pointerId);
      event.preventDefault();
    }
  }

  // Handle pointer move (resize in progress)
  @HostListener('pointermove', ['$event'])
  onPointerMove(event: PointerEvent) {
    if (!this.isResizing) return;

    this.zone.runOutsideAngular(() => {
      if (this.animationFrame) {
        cancelAnimationFrame(this.animationFrame);
      }
      this.animationFrame = requestAnimationFrame(() => {
        const diff = event.clientY - this.startY;
        const newHeight = Math.max(this.startHeight + diff, 60);
        this.params.node.setRowHeight(newHeight);
        this.params.api.onRowHeightChanged();
      });
    });
  }

  // Handle pointer up (stop resizing)
  @HostListener('pointerup', ['$event'])
  onPointerUp(event: PointerEvent) {
    if (this.isResizing) {
      this.isResizing = false;
      if (this.animationFrame) {
        cancelAnimationFrame(this.animationFrame);
        this.animationFrame = null;
      }
      this.cd.markForCheck();
    }
  }

  // Handle click to temporarily show the resizer
  @HostListener('click')
  onHostClick() {
    if (!this.isResizing) {
      this.tempVisible = true;
      this.cd.markForCheck();
      if (this.tempVisibleTimeout) {
        clearTimeout(this.tempVisibleTimeout);
      }
      this.tempVisibleTimeout = setTimeout(() => {
        this.tempVisible = false;
        this.cd.markForCheck();
      }, 5000);
    }
  }

  // New method for handling double-click to set row height based on content
  @HostListener('dblclick', ['$event'])
  onDoubleClick(event: MouseEvent) {
    // Get the content of the role, goal, and backstory
    const roleText = this.params.data.role || '';
    const goalText = this.params.data.goal || '';
    const backstoryText = this.params.data.backstory || '';

    // Calculate the content height based on the length of the text
    const maxContentHeight = Math.max(
      this.calculateTextHeight(roleText),
      this.calculateTextHeight(goalText),
      this.calculateTextHeight(backstoryText)
    );

    // Add some padding to the calculated height
    const newHeight = Math.max(maxContentHeight + 20, 60); // Minimum height 60px

    // Set the row height and trigger AG Grid to update it
    this.params.node.setRowHeight(newHeight);
    this.params.api.onRowHeightChanged();
  }

  // Helper method to calculate text height based on the content
  private calculateTextHeight(text: string): number {
    // You can improve this calculation, currently we're assuming 20px per line of text
    const lines = Math.ceil(text.length / 36); // Approx 50 chars per line
    return lines * 20; // 20px per line
  }

  // Refresh method
  refresh(params: any): boolean {
    this.params = params;
    return false;
  }

  ngOnDestroy() {
    if (this.tempVisibleTimeout) {
      clearTimeout(this.tempVisibleTimeout);
    }
    if (this.animationFrame) {
      cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
  }
}
