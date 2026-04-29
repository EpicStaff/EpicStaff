import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    Component,
    ElementRef,
    OnDestroy,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';
import { fromEvent, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-human-input-header',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    template: `
        <div
            class="header-container"
            #headerContainer
        >
            <app-svg-icon
                icon="hand-click"
                size="24px"
            />
        </div>

        <ng-template #tooltipTemplate>
            <div class="tooltip">Ask for feedback</div>
        </ng-template>
    `,
    styles: [
        `
            :host {
                width: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                padding-right: 3px;
            }
            .header-container {
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .tooltip {
                background-color: #2a2a2a;
                color: #d9d9de;
                padding: 6px 10px;
                border-radius: 4px;
                font-size: 12px;
                white-space: nowrap;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
                border: 1px solid #404040;
            }
        `,
    ],
})
export class HumanInputHeaderComponent implements OnDestroy, AfterViewInit {
    @ViewChild('headerContainer', { static: true }) headerContainer!: ElementRef;
    @ViewChild('tooltipTemplate', { static: true })
    tooltipTemplate!: TemplateRef<unknown>;

    params!: IHeaderParams;
    private destroy$ = new Subject<void>();
    private overlayRef: OverlayRef | null = null;

    constructor(
        private overlay: Overlay,
        private viewContainerRef: ViewContainerRef
    ) {}

    ngAfterViewInit(): void {
        const element = this.headerContainer.nativeElement;

        fromEvent(element, 'mouseenter')
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => {
                this.showTooltip();
            });

        fromEvent(element, 'mouseleave')
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => {
                this.hideTooltip();
            });
    }

    private showTooltip(): void {
        if (this.overlayRef) {
            return;
        }

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(this.headerContainer.nativeElement)
            .withPositions([
                {
                    originX: 'center',
                    originY: 'top',
                    overlayX: 'center',
                    overlayY: 'bottom',
                    offsetY: -8,
                },
            ]);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.close(),
        });

        const portal = new TemplatePortal(this.tooltipTemplate, this.viewContainerRef);
        this.overlayRef.attach(portal);
    }

    private hideTooltip(): void {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
    }

    agInit(params: IHeaderParams): void {
        this.params = params;
    }

    refresh(params: IHeaderParams): boolean {
        void params;
        return false;
    }

    ngOnDestroy(): void {
        this.hideTooltip();
        this.destroy$.next();
        this.destroy$.complete();
    }
}
