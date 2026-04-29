import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-conditional-edge-node',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    template: `
        <svg
            [attr.width]="width"
            [attr.height]="height"
            [attr.viewBox]="'0 0 ' + width + ' ' + height"
        >
            <path
                [attr.d]="roundedDiamondPath"
                [style.fill]="'var(--color-nodes-background)'"
                [style.stroke]="'var(--edge-node-border-color)'"
                stroke-width="2"
            ></path>
            <foreignObject
                [attr.x]="contentX"
                [attr.y]="contentY"
                [attr.width]="contentWidth"
                [attr.height]="contentHeight"
            >
                <div class="edge-content">
                    <app-svg-icon
                        icon="route-alt-left"
                        size="25px"
                    ></app-svg-icon>
                    <span>Conditional Edge</span>
                </div>
            </foreignObject>
        </svg>
    `,
    styles: [
        `
            :host {
                display: block;
            }

            svg {
                overflow: visible;
            }

            .edge-content {
                width: 100%;
                height: 100%;
                display: flex;
                flex-direction: row;
                justify-content: center;
                align-items: center;
                gap: 1rem;
                font-size: 16px;
                color: #fff;

                app-svg-icon {
                    transform: rotate(90deg);
                    color: var(--edge-node-accent-color);
                }
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConditionalEdgeNodeComponent {
    @Input() width: number = 300;
    @Input() height: number = 180;

    @Input() cornerRadius: number = 10;

    get roundedDiamondPath(): string {
        const w = this.width;
        const h = this.height;

        const r = Math.min(this.cornerRadius, w / 2, h / 2);

        const top = { x: w / 2, y: 0 };
        const right = { x: w, y: h / 2 };
        const bottom = { x: w / 2, y: h };
        const left = { x: 0, y: h / 2 };

        const topRightOffset = {
            x: top.x + (right.x - top.x) * (r / Math.hypot(w / 2, h / 2)),
            y: top.y + (right.y - top.y) * (r / Math.hypot(w / 2, h / 2)),
        };
        const topLeftOffset = {
            x: top.x + (left.x - top.x) * (r / Math.hypot(w / 2, h / 2)),
            y: top.y + (left.y - top.y) * (r / Math.hypot(w / 2, h / 2)),
        };

        const rightTopOffset = {
            x: right.x + (top.x - right.x) * (r / Math.hypot(w / 2, h / 2)),
            y: right.y + (top.y - right.y) * (r / Math.hypot(w / 2, h / 2)),
        };
        const rightBottomOffset = {
            x: right.x + (bottom.x - right.x) * (r / Math.hypot(w / 2, h / 2)),
            y: right.y + (bottom.y - right.y) * (r / Math.hypot(w / 2, h / 2)),
        };

        const bottomRightOffset = {
            x: bottom.x + (right.x - bottom.x) * (r / Math.hypot(w / 2, h / 2)),
            y: bottom.y + (right.y - bottom.y) * (r / Math.hypot(w / 2, h / 2)),
        };
        const bottomLeftOffset = {
            x: bottom.x + (left.x - bottom.x) * (r / Math.hypot(w / 2, h / 2)),
            y: bottom.y + (left.y - bottom.y) * (r / Math.hypot(w / 2, h / 2)),
        };

        const leftBottomOffset = {
            x: left.x + (bottom.x - left.x) * (r / Math.hypot(w / 2, h / 2)),
            y: left.y + (bottom.y - left.y) * (r / Math.hypot(w / 2, h / 2)),
        };
        const leftTopOffset = {
            x: left.x + (top.x - left.x) * (r / Math.hypot(w / 2, h / 2)),
            y: left.y + (top.y - left.y) * (r / Math.hypot(w / 2, h / 2)),
        };

        return `
      M ${topLeftOffset.x} ${topLeftOffset.y}
      Q ${top.x} ${top.y} ${topRightOffset.x} ${topRightOffset.y}
      L ${rightTopOffset.x} ${rightTopOffset.y}
      Q ${right.x} ${right.y} ${rightBottomOffset.x} ${rightBottomOffset.y}
      L ${bottomRightOffset.x} ${bottomRightOffset.y}
      Q ${bottom.x} ${bottom.y} ${bottomLeftOffset.x} ${bottomLeftOffset.y}
      L ${leftBottomOffset.x} ${leftBottomOffset.y}
      Q ${left.x} ${left.y} ${leftTopOffset.x} ${leftTopOffset.y}
      Z
    `;
    }

    get contentX(): number {
        return this.width * 0.18;
    }
    get contentY(): number {
        return this.height * 0.32;
    }
    get contentWidth(): number {
        return this.width * 0.64;
    }
    get contentHeight(): number {
        return this.height * 0.36;
    }
}
