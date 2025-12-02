import {
    Component,
    Input,
    ChangeDetectionStrategy,
    ElementRef,
    ViewChild,
    OnDestroy,
    NgZone,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AppIconComponent } from '../app-icon/app-icon.component';
import {
    Overlay,
    OverlayModule,
    OverlayRef,
    ConnectedPosition,
} from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import { TooltipContentComponent } from './tooltip-content.component';
import { take, fromEvent, filter } from 'rxjs';

@Component({
    selector: 'app-help-tooltip',
    standalone: true,
    imports: [CommonModule, AppIconComponent, OverlayModule],
    template: `
        <div class="help-tooltip-container">
            <span
                #tooltipTrigger
                class="help-icon-wrapper"
                (mouseenter)="showTooltip()"
                (mouseleave)="onMouseLeave()"
                tabindex="0"
                (focus)="showTooltip()"
                (blur)="hideTooltip()"
            >
                <app-icon icon="ui/help" [size]="'1.2rem'"></app-icon>
            </span>
        </div>
    `,
    styles: [
        `
            .help-tooltip-container {
                position: relative;

                align-items: center;
            }
            .help-icon-wrapper {
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                outline: none;
                position: relative;
                color: rgba(255, 255, 255, 0.8);
                transition: color 0.2s ease;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.1);

                &:hover {
                    color: rgba(255, 255, 255, 1);
                    background: rgba(255, 255, 255, 0.2);
                }
            }

            :host ::ng-deep .tooltip-overlay-panel {
                z-index: 9999 !important;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HelpTooltipComponent implements OnDestroy {
    @Input() text = '';
    @Input() position: 'top' | 'bottom' | 'left' | 'right' = 'top';
    @ViewChild('tooltipTrigger') tooltipTrigger!: ElementRef;

    private overlayRef: OverlayRef | null = null;
    private tooltipInstance: TooltipContentComponent | null = null;
    private tooltipHover = false;

    constructor(private overlay: Overlay, private ngZone: NgZone) {}

    showTooltip() {
        if (this.overlayRef) {
            return;
        }

        if (!this.text) {
            return;
        }

        // Create overlay for the tooltip
        this.overlayRef = this.overlay.create({
            hasBackdrop: false,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            positionStrategy: this.overlay
                .position()
                .flexibleConnectedTo(this.tooltipTrigger)
                .withPositions([this.getPositionStrategy()]),
            panelClass: 'tooltip-overlay-panel',
        });

        // Create portal from tooltip content component
        const tooltipPortal = new ComponentPortal(TooltipContentComponent);
        const tooltipRef = this.overlayRef.attach(tooltipPortal);

        // Store instance reference
        this.tooltipInstance = tooltipRef.instance;

        // Pass the text to the tooltip component
        this.tooltipInstance.text = this.text;

        // Add event listeners to the tooltip element
        this.ngZone.runOutsideAngular(() => {
            setTimeout(() => {
                if (this.overlayRef) {
                    const tooltipElement = this.overlayRef.overlayElement;

                    // Listen for mouseenter on tooltip
                    fromEvent(tooltipElement, 'mouseenter')
                        .pipe(take(1))
                        .subscribe(() => {
                            this.ngZone.run(() => {
                                this.tooltipHover = true;
                            });
                        });

                    // Listen for mouseleave on tooltip
                    fromEvent(tooltipElement, 'mouseleave')
                        .pipe(take(1))
                        .subscribe(() => {
                            this.ngZone.run(() => {
                                this.tooltipHover = false;
                                this.hideTooltip();
                            });
                        });
                }
            }, 0);
        });
    }

    onMouseLeave(): void {
        // Set a small delay to check if mouse moved to tooltip
        setTimeout(() => {
            if (!this.tooltipHover) {
                this.hideTooltip();
            }
        }, 50);
    }

    private getPositionStrategy(): ConnectedPosition {
        // Return position strategy based on the position input
        switch (this.position) {
            case 'bottom':
                return {
                    originX: 'center' as const,
                    originY: 'bottom' as const,
                    overlayX: 'center' as const,
                    overlayY: 'top' as const,
                    offsetY: 8,
                };
            case 'left':
                return {
                    originX: 'start' as const,
                    originY: 'center' as const,
                    overlayX: 'end' as const,
                    overlayY: 'center' as const,
                    offsetX: -8,
                };
            case 'right':
                return {
                    originX: 'end' as const,
                    originY: 'center' as const,
                    overlayX: 'start' as const,
                    overlayY: 'center' as const,
                    offsetX: 8,
                };
            default: // 'top' or any other value
                return {
                    originX: 'center' as const,
                    originY: 'top' as const,
                    overlayX: 'center' as const,
                    overlayY: 'bottom' as const,
                    offsetY: -8,
                };
        }
    }

    hideTooltip() {
        if (this.overlayRef && !this.tooltipHover) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = null;
            this.tooltipInstance = null;
        }
    }

    ngOnDestroy() {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
            this.tooltipInstance = null;
        }
    }
}
