import { Overlay, OverlayModule, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal, PortalModule } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, Input, OnDestroy, OnInit } from '@angular/core';

@Component({
    selector: 'app-tooltip-content',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="tooltip-container">
            {{ text }}
            <span class="tooltip-arrow"></span>
        </div>
    `,
    styleUrls: ['./tooltip.component.scss'],
})
export class TooltipContentComponent {
    @Input() public text: string = '';
}

@Component({
    selector: 'app-tooltip',
    standalone: true,
    imports: [CommonModule, OverlayModule, PortalModule],
    template: ``,
    styleUrls: ['./tooltip.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TooltipComponent implements OnInit, OnDestroy {
    @Input() public text: string = '';
    @Input() public set visible(value: boolean) {
        if (value) {
            this.showTooltip();
        } else {
            this.hideTooltip();
        }
        this._visible = value;
    }
    public get visible(): boolean {
        return this._visible;
    }
    @Input() public class: string = '';

    private _visible: boolean = false;
    private overlayRef: OverlayRef | null = null;

    constructor(
        private overlay: Overlay,
        private elementRef: ElementRef
    ) {}

    ngOnInit(): void {
        // Create the overlay config
        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(this.elementRef)
            .withPositions([
                {
                    originX: 'end',
                    originY: 'center',
                    overlayX: 'start',
                    overlayY: 'center',
                    offsetX: 10,
                },
            ]);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: false,
        });
    }

    ngOnDestroy(): void {
        this.hideTooltip();
        if (this.overlayRef) {
            this.overlayRef.dispose();
        }
    }

    private showTooltip(): void {
        if (!this.overlayRef || this.overlayRef.hasAttached()) {
            return;
        }

        const tooltipPortal = new ComponentPortal(TooltipContentComponent);
        const tooltipRef = this.overlayRef.attach(tooltipPortal);
        tooltipRef.instance.text = this.text;
    }

    private hideTooltip(): void {
        if (this.overlayRef && this.overlayRef.hasAttached()) {
            this.overlayRef.detach();
        }
    }
}
