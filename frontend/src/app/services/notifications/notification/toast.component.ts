import { animate, state, style, transition, trigger } from '@angular/animations';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';

import { ToastMessage, ToastPosition, ToastService } from '../toast.service';

@Component({
    selector: 'app-toast',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="toast-container" [ngClass]="position">
            <div
                *ngFor="let toast of toasts"
                [@toastAnimation]="position"
                class="toast-item"
                [ngClass]="toast.type"
                (click)="closeToast(toast.id)"
            >
                <div class="toast-content">
                    <div>
                        <i [class]="getIconClass(toast.type)"></i>
                    </div>
                    <span class="toast-message">{{ toast.message }}</span>
                </div>
                <button class="toast-close-btn" (click)="closeToast(toast.id); $event.stopPropagation()">
                    <i class="ti ti-x"></i>
                </button>
            </div>
        </div>
    `,
    styles: [
        `
            .toast-container {
                position: fixed;
                z-index: 9999;
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

                &.top-left {
                    top: 20px;
                    left: 20px;
                    flex-direction: column;
                }

                &.top-center {
                    top: 20px;
                    left: 50%;
                    transform: translateX(-50%);
                    flex-direction: column;
                }

                &.bottom-right {
                    bottom: 20px;
                    right: 20px;
                    flex-direction: column-reverse;
                }

                &.bottom-left {
                    bottom: 20px;
                    left: 20px;
                    flex-direction: column-reverse;
                }

                &.bottom-center {
                    bottom: 20px;
                    left: 50%;
                    transform: translateX(-50%);
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

                    i {
                        margin-right: 16px;
                    }
                }

                &:hover {
                    transform: translateY(-2px);
                    background-color: #2a2a2a;
                }

                &.success {
                    i {
                        color: #4caf50;
                    }
                }

                &.error {
                    i {
                        color: #f44336;
                    }
                }

                &.warning {
                    i {
                        color: #ff9800;
                    }
                }

                &.info {
                    i {
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
                font-size: 14px;
                cursor: pointer;
                padding: 4px;
                margin-left: 10px;
                flex-shrink: 0;

                &:hover {
                    color: #e0e0e0;
                }
            }
        `,
    ],
    animations: [
        trigger('toastAnimation', [
            // Top positions - slide from top
            state(
                'top-center',
                style({
                    opacity: 1,
                    transform: 'translateY(0)',
                })
            ),
            state(
                'top-right',
                style({
                    opacity: 1,
                    transform: 'translateY(0)',
                })
            ),
            state(
                'top-left',
                style({
                    opacity: 1,
                    transform: 'translateY(0)',
                })
            ),

            // Bottom positions - slide from right
            state(
                'bottom-right',
                style({
                    opacity: 1,
                    transform: 'translateX(0)',
                })
            ),
            state(
                'bottom-left',
                style({
                    opacity: 1,
                    transform: 'translateX(0)',
                })
            ),
            state(
                'bottom-center',
                style({
                    opacity: 1,
                    transform: 'translateX(0)',
                })
            ),

            // Top positions animations (from top)
            transition('void => top-center, void => top-right, void => top-left', [
                style({
                    opacity: 0,
                    transform: 'translateY(-100%)',
                }),
                animate('300ms ease-out'),
            ]),
            transition('top-center => void, top-right => void, top-left => void', [
                animate(
                    '200ms ease-in',
                    style({
                        opacity: 0,
                        transform: 'translateY(-100%)',
                    })
                ),
            ]),

            // Bottom positions animations (from right)
            transition('void => bottom-right, void => bottom-center, void => bottom-left', [
                style({
                    opacity: 0,
                    transform: 'translateX(100%)',
                }),
                animate('300ms ease-out'),
            ]),
            transition('bottom-right => void, bottom-center => void, bottom-left => void', [
                animate(
                    '200ms ease-in',
                    style({
                        opacity: 0,
                        transform: 'translateX(100%)',
                    })
                ),
            ]),
        ]),
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

        // Get position from service if not explicitly provided via input
        if (!this.position) {
            this.position = this.toastService.defaultPosition;
        }
    }

    public closeToast(id: number): void {
        this.toastService.remove(id);
    }

    public getIconClass(type: string): string {
        switch (type) {
            case 'success':
                return 'ti ti-check';
            case 'error':
                return 'ti ti-alert-circle';
            case 'warning':
                return 'ti ti-alert-triangle';
            case 'info':
                return 'ti ti-info-circle';
            default:
                return 'ti ti-bell';
        }
    }

    ngOnDestroy(): void {
        this.subscription.unsubscribe();
    }
}
