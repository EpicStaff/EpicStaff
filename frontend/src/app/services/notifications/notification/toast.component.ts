import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';

import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ToastMessage, ToastPosition, ToastService } from '../toast.service';

@Component({
    selector: 'app-toast',
    imports: [CommonModule, AppSvgIconComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="toast-container"
            [ngClass]="position"
        >
            @for (toast of toasts; track toast.id) {
                <div
                    animate.enter="toast-enter"
                    animate.leave="toast-leave"
                    class="toast-item"
                    [ngClass]="toast.type"
                    (click)="closeToast(toast.id)"
                >
                    <div class="toast-content">
                        <div class="toast-icon-wrapper">
                            <app-svg-icon
                                [icon]="getIconId(toast.type)"
                                size="20px"
                            ></app-svg-icon>
                        </div>
                        <span class="toast-message">{{ toast.message }}</span>
                    </div>
                    <button
                        class="toast-close-btn"
                        (click)="closeToast(toast.id); $event.stopPropagation()"
                    >
                        <app-svg-icon
                            icon="x"
                            size="16px"
                        ></app-svg-icon>
                    </button>
                </div>
            }
        </div>
    `,
    styles: [
        `
            .toast-container {
                position: fixed;
                z-index: 20000;
                display: flex;
                gap: 10px;
                max-width: 350px;
                width: 350px;
                max-height: 80vh;
                overflow-x: hidden;
                overflow-y: auto;
                scrollbar-width: none;
                -ms-overflow-style: none;

                &::-webkit-scrollbar {
                    display: none;
                }

                &.top-right {
                    top: 20px;
                    right: 20px;
                    flex-direction: column;
                }

                &.bottom-right {
                    bottom: 20px;
                    right: 20px;
                    flex-direction: column-reverse;
                }
            }

            .toast-item {
                width: 100%;
                padding: 12px 16px;
                border-radius: 6px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                background-color: #1e1e1e;
                color: #e0e0e0;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
                cursor: pointer;
                transition:
                    transform 0.2s ease,
                    background-color 0.2s ease;
                border: 1px solid #2a2a2a;

                .toast-content {
                    display: flex;
                    align-items: center;

                    .toast-icon-wrapper {
                        display: inline-flex;
                        align-items: center;
                        flex-shrink: 0;
                        margin-right: 16px;
                    }
                }

                &:hover {
                    transform: translateY(-2px);
                    background-color: #2a2a2a;
                }

                &.success {
                    app-svg-icon {
                        color: #4caf50;
                    }
                }

                &.error {
                    app-svg-icon {
                        color: #f44336;
                    }
                }

                &.warning {
                    app-svg-icon {
                        color: #ff9800;
                    }
                }

                &.info {
                    app-svg-icon {
                        color: #2196f3;
                    }
                }
            }

            .toast-message {
                font-size: 14px;
                color: #e0e0e0;
                display: -webkit-box;
                -webkit-line-clamp: 3;
                -webkit-box-orient: vertical;
                overflow: hidden;
                text-overflow: ellipsis;
                line-height: 1.4;
                max-height: 4.2em;
                word-break: break-word;
                min-width: 0;
            }

            .toast-close-btn {
                background: transparent;
                border: none;
                color: #a0a0a0;
                cursor: pointer;
                padding: 4px;
                margin-left: 10px;
                flex-shrink: 0;

                &:hover {
                    color: #e0e0e0;
                }
            }

            @keyframes toast-enter-top {
                from {
                    opacity: 0;
                    transform: translateY(-100%);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            @keyframes toast-leave-top {
                from {
                    opacity: 1;
                    transform: translateY(0);
                }
                to {
                    opacity: 0;
                    transform: translateY(-100%);
                }
            }

            @keyframes toast-enter-right {
                from {
                    opacity: 0;
                    transform: translateX(100%);
                }
                to {
                    opacity: 1;
                    transform: translateX(0);
                }
            }

            @keyframes toast-leave-right {
                from {
                    opacity: 1;
                    transform: translateX(0);
                }
                to {
                    opacity: 0;
                    transform: translateX(100%);
                }
            }

            .toast-container.top-right {
                .toast-item.toast-enter {
                    animation: toast-enter-top 300ms ease-out;
                }

                .toast-item.toast-leave {
                    animation: toast-leave-top 200ms ease-in;
                }
            }

            .toast-container.bottom-right {
                .toast-item.toast-enter {
                    animation: toast-enter-right 300ms ease-out;
                }

                .toast-item.toast-leave {
                    animation: toast-leave-right 200ms ease-in;
                }
            }

            @media (prefers-reduced-motion: reduce) {
                .toast-item.toast-enter,
                .toast-item.toast-leave {
                    animation-duration: 1ms;
                }
            }
        `,
    ],
})
export class ToastComponent implements OnInit, OnDestroy {
    @Input() position: ToastPosition = 'bottom-right';

    public toasts: ToastMessage[] = [];
    private subscription = new Subscription();

    constructor(
        private toastService: ToastService,
        private cdr: ChangeDetectorRef
    ) {}

    ngOnInit(): void {
        this.subscription.add(
            this.toastService.toasts$.subscribe((toasts) => {
                this.toasts = toasts.filter(
                    (toast) => this.toastService.getPositionForToast(toast.id) === this.position
                );
                this.cdr.markForCheck();
            })
        );

        if (!this.position) {
            this.position = this.toastService.defaultPosition;
        }
    }

    public closeToast(id: number): void {
        this.toastService.remove(id);
    }

    public getIconId(type: string): string {
        switch (type) {
            case 'success':
                return 'check';
            case 'error':
                return 'alert-circle';
            case 'warning':
                return 'warning';
            case 'info':
                return 'info-circle';
            default:
                return 'info-circle';
        }
    }

    ngOnDestroy(): void {
        this.subscription.unsubscribe();
    }
}
