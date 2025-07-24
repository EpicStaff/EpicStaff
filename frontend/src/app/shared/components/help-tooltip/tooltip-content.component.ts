import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-tooltip-content',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="tooltip-content">
      {{ text }}
    </div>
  `,
  styles: [
    `
      .tooltip-content {
        background: #232323;
        color: #fff;
        padding: 0.75rem 1rem;
        border-radius: 8px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
        width: auto;
        min-width: 300px;
        max-width: 400px;
        font-size: 0.95rem;
        white-space: pre-wrap;
        pointer-events: auto;
        user-select: text;
        text-align: left;
        z-index: 1000;
        line-height: 1.5;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TooltipContentComponent {
  @Input() text = '';
}
