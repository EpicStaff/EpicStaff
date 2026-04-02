import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
import { ViewContainerRef } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';
import { fromEvent, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'app-human-input-header',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="header-container" #headerContainer>
            <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="icon icon-tabler icons-tabler-outline icon-tabler-hand-click"
            >
                <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                <path d="M8 13v-8.5a1.5 1.5 0 0 1 3 0v7.5" />
                <path d="M11 11.5v-2a1.5 1.5 0 0 1 3 0v2.5" />
                <path d="M14 10.5a1.5 1.5 0 0 1 3 0v1.5" />
                <path
                    d="M17 11.5a1.5 1.5 0 0 1 3 0v4.5a6 6 0 0 1 -6 6h-2h.208a6 6 0 0 1 -5.012 -2.7l-.196 -.3c-.312 -.479 -1.407 -2.388 -3.286 -5.728a1.5 1.5 0 0 1 .536 -2.022a1.867 1.867 0 0 1 2.28 .28l1.47 1.47"
                />
                <path d="M5 3l-1 -1" />
                <path d="M4 7h-1" />
                <path d="M14 3l1 -1" />
                <path d="M15 6h1" />
            </svg>
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
            .icon {
                height: 24px;
                width: 24px;
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

        // Mouse enter event
        fromEvent(element, 'mouseenter')
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => {
                this.showTooltip();
            });

        // Mouse leave event
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
