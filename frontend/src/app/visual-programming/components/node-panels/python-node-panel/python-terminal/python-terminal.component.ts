import { CommonModule, DOCUMENT } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    Inject,
    input,
    NgZone,
    OnDestroy,
    output,
    Renderer2,
    signal,
    ViewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { TerminalLogEntry } from './terminal-log.model';

export type TerminalStatus = 'idle' | 'processing' | 'done' | 'error';

@Component({
    standalone: true,
    selector: 'app-python-terminal',
    imports: [CommonModule, AppSvgIconComponent, MatTooltipModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div
            class="python-terminal"
            [class.is-collapsed]="isCollapsed()"
        >
            @if (!isCollapsed()) {
                <div
                    class="terminal-resize-handle"
                    (pointerdown)="onResizeStart($event)"
                ></div>
            }
            <div class="terminal-header">
                <div class="terminal-title-group">
                    @if (status() !== 'idle') {
                        <span
                            class="status-dot"
                            [class.status-processing]="status() === 'processing'"
                            [class.status-done]="status() === 'done'"
                            [class.status-error]="status() === 'error'"
                            [matTooltip]="statusTitle()"
                            matTooltipPosition="above"
                            [attr.aria-label]="statusTitle()"
                        ></span>
                    }
                    <span class="terminal-title">Terminal Output</span>
                </div>
                <div class="terminal-actions">
                    @if (!isCollapsed()) {
                        <button
                            type="button"
                            class="icon-btn"
                            matTooltip="Clear terminal"
                            matTooltipPosition="above"
                            aria-label="Clear terminal"
                            (click)="clearLogs.emit()"
                        >
                            <app-svg-icon
                                icon="trash"
                                size="14px"
                            />
                        </button>
                    }
                    <button
                        type="button"
                        class="icon-btn"
                        [matTooltip]="isCollapsed() ? 'Show terminal' : 'Hide terminal'"
                        matTooltipPosition="above"
                        [attr.aria-label]="isCollapsed() ? 'Show terminal' : 'Hide terminal'"
                        (click)="toggleCollapsed()"
                    >
                        <app-svg-icon
                            [icon]="isCollapsed() ? 'chevron-up' : 'chevron-down'"
                            size="14px"
                        />
                    </button>
                </div>
            </div>
            @if (!isCollapsed()) {
                <div
                    class="terminal-body"
                    #terminalBody
                    [style.height.px]="terminalHeight()"
                >
                    @for (entry of logs(); track $index) {
                        <div
                            class="terminal-line"
                            [ngClass]="'log-' + entry.type"
                        >
                            <span class="timestamp">{{ formatTime(entry.timestamp) }}</span>
                            <span class="message">{{ entry.message }}</span>
                        </div>
                    }
                </div>
            }
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
            }

            .python-terminal {
                position: relative;
                width: 100%;
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-top: none;
                border-radius: 0 0 8px 8px;
                background: var(--color-ks-card-background, #1e1e1e);
                font-family: 'Fira Code', 'Consolas', 'Courier New', monospace;
                font-size: 0.8rem;
            }

            .terminal-resize-handle {
                position: absolute;
                top: -3px;
                left: 0;
                right: 0;
                height: 6px;
                cursor: ns-resize;
                z-index: 5;

                &:hover {
                    background: rgba(104, 95, 255, 0.3);
                }
            }

            .terminal-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 0.25rem 0.75rem;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                color: #8b949e;
                font-size: 0.75rem;
                user-select: none;
            }

            .terminal-title-group {
                display: flex;
                align-items: center;
                gap: 0.4rem;
            }

            .status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
                display: inline-block;

                &.status-processing {
                    background: #ffc14d;
                    box-shadow: 0 0 0 0 rgba(255, 193, 77, 0.6);
                    animation: terminal-status-pulse 1.4s infinite ease-in-out;
                }
                &.status-done {
                    background: #3fb950;
                }
                &.status-error {
                    background: #f85149;
                }
            }

            @keyframes terminal-status-pulse {
                0% {
                    opacity: 1;
                    box-shadow: 0 0 0 0 rgba(255, 193, 77, 0.55);
                }
                70% {
                    opacity: 0.7;
                    box-shadow: 0 0 0 6px rgba(255, 193, 77, 0);
                }
                100% {
                    opacity: 1;
                    box-shadow: 0 0 0 0 rgba(255, 193, 77, 0);
                }
            }

            .terminal-actions {
                display: flex;
                align-items: center;
                gap: 0.25rem;
            }

            .icon-btn {
                display: flex;
                align-items: center;
                justify-content: center;
                background: transparent;
                border: none;
                color: #8b949e;
                cursor: pointer;
                padding: 2px;
                border-radius: 4px;

                &:hover {
                    color: #d4d4d4;
                    background: rgba(255, 255, 255, 0.1);
                }
            }

            .terminal-body {
                overflow-y: auto;
                padding: 0.5rem 0.75rem;
                min-height: 60px;
                max-height: 500px;
            }

            .terminal-line {
                line-height: 1.6;
                white-space: pre-wrap;
                word-break: break-all;
            }

            .timestamp {
                color: #6e7681;
                margin-right: 0.5rem;
            }

            .log-info .message {
                color: #8b949e;
            }

            .log-polling .message {
                color: #8b949e;
            }

            .log-stdout .message {
                color: #e3b341;
            }

            .log-stderr .message {
                color: #f85149;
            }

            .log-result .message {
                color: #3fb950;
            }

            .log-error .message {
                color: #f85149;
            }
        `,
    ],
})
export class PythonTerminalComponent implements OnDestroy {
    logs = input<TerminalLogEntry[]>([]);
    terminalHeight = input<number>(150);
    status = input<TerminalStatus>('idle');

    statusTitle = computed(() => {
        switch (this.status()) {
            case 'processing':
                return 'Processing…';
            case 'done':
                return 'Completed successfully';
            case 'error':
                return 'Failed';
            default:
                return '';
        }
    });

    heightChange = output<number>();
    clearLogs = output<void>();

    isCollapsed = signal(false);

    @ViewChild('terminalBody') terminalBody!: ElementRef<HTMLDivElement>;

    private isResizing = false;
    private startY = 0;
    private startHeight = 0;
    private unlistenPointerMove?: () => void;
    private unlistenPointerUp?: () => void;

    constructor(
        private renderer: Renderer2,
        private ngZone: NgZone,
        @Inject(DOCUMENT) private document: Document
    ) {
        effect(() => {
            this.logs();
            this.scrollToBottom();
        });
    }

    toggleCollapsed(): void {
        this.isCollapsed.update((v) => !v);
    }

    formatTime(date: Date): string {
        const h = String(date.getHours()).padStart(2, '0');
        const m = String(date.getMinutes()).padStart(2, '0');
        const s = String(date.getSeconds()).padStart(2, '0');
        return `[${h}:${m}:${s}]`;
    }

    onResizeStart(event: PointerEvent): void {
        this.isResizing = true;
        this.startY = event.clientY;
        this.startHeight = this.terminalBody?.nativeElement?.clientHeight ?? this.terminalHeight();
        event.preventDefault();

        this.ngZone.runOutsideAngular(() => {
            this.unlistenPointerMove = this.renderer.listen(this.document, 'pointermove', (e: PointerEvent) =>
                this.onPointerMove(e)
            );
            this.unlistenPointerUp = this.renderer.listen(this.document, 'pointerup', () => this.onPointerUp());
        });
    }

    private onPointerMove(event: PointerEvent): void {
        if (!this.isResizing) return;

        const delta = this.startY - event.clientY;
        const newHeight = Math.min(500, Math.max(60, this.startHeight + delta));

        requestAnimationFrame(() => {
            this.ngZone.run(() => {
                this.heightChange.emit(newHeight);
            });
        });
    }

    private onPointerUp(): void {
        if (this.isResizing) {
            this.isResizing = false;
            if (this.unlistenPointerMove) this.unlistenPointerMove();
            if (this.unlistenPointerUp) this.unlistenPointerUp();
        }
    }

    private scrollToBottom(): void {
        setTimeout(() => {
            const el = this.terminalBody?.nativeElement;
            if (el) {
                const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
                if (isNearBottom) {
                    el.scrollTop = el.scrollHeight;
                }
            }
        });
    }

    ngOnDestroy(): void {
        if (this.unlistenPointerMove) this.unlistenPointerMove();
        if (this.unlistenPointerUp) this.unlistenPointerUp();
    }
}
