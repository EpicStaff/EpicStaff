import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import { CommonModule } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, TemplateRef, ViewChild } from '@angular/core';
import { ViewContainerRef } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';
import { fromEvent, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'app-delegation-header',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div
            class="header-container"
            #headerContainer
        >
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
                class="icon icon-tabler icons-tabler-outline icon-tabler-users"
            >
                <path
                    stroke="none"
                    d="M0 0h24v24H0z"
                    fill="none"
                />
                <path d="M9 7m-4 0a4 4 0 1 0 8 0a4 4 0 1 0 -8 0" />
                <path d="M3 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                <path d="M21 21v-2a4 4 0 0 0 -3 -3.85" />
            </svg>
        </div>

        <ng-template #tooltipTemplate>
            <div class="tooltip">Allow delegation</div>
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
export class DelegationHeaderComponent implements OnDestroy, AfterViewInit {
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
