import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
import { ViewContainerRef } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';
import { fromEvent, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'app-memory-header',
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
                class="icon icon-tabler icons-tabler-outline icon-tabler-database"
            >
                <path stroke="none" d="M0 0h24v24H0z" fill="none" />
                <path d="M12 6m-8 0a8 3 0 1 0 16 0a8 3 0 1 0 -16 0" />
                <path d="M4 6v6a8 3 0 0 0 16 0v-6" />
                <path d="M4 12v6a8 3 0 0 0 16 0v-6" />
            </svg>
        </div>

        <ng-template #tooltipTemplate>
            <div class="tooltip">Use memory</div>
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
export class MemoryHeaderComponent implements OnDestroy, AfterViewInit {
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
