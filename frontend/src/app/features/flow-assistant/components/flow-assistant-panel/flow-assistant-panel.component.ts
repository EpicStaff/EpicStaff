import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    HostListener,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MarkdownModule } from 'ngx-markdown';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { FlowAssistantService } from '../../flow-assistant.service';
import { ActionItem, EfTable, FlowAssistantMessage } from '../../models/flow-assistant.model';
import { stripTrailingEllipsis, toolStatusFor } from '../../services/tool-labels';
import { FlowAssistantActionsComponent } from '../flow-assistant-actions/flow-assistant-actions.component';
import { FlowAssistantSettingsComponent } from '../flow-assistant-settings/flow-assistant-settings.component';
import { FlowAssistantSidebarComponent } from '../flow-assistant-sidebar/flow-assistant-sidebar.component';
import { FlowAssistantTableComponent } from '../flow-assistant-table/flow-assistant-table.component';
import {
    FlowAssistantToolPillComponent,
    ToolPillEntry,
} from '../flow-assistant-tool-pill/flow-assistant-tool-pill.component';

const MIN_PANEL_WIDTH = 300;
const MAX_PANEL_WIDTH = 800;
const SIDEBAR_OPEN_KEY = 'flow_assistant_sidebar_open';
const SCROLL_AT_BOTTOM_THRESHOLD = 50;

type ResizeDirection = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

@Component({
    selector: 'app-flow-assistant-panel',
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        MarkdownModule,
        OverlayModule,
        AppSvgIconComponent,
        FlowAssistantSettingsComponent,
        FlowAssistantSidebarComponent,
        FlowAssistantTableComponent,
        FlowAssistantActionsComponent,
        FlowAssistantToolPillComponent,
    ],
    templateUrl: './flow-assistant-panel.component.html',
    styleUrls: ['./flow-assistant-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    host: {
        '[class.mode-floating]': 'isFloatingMode()',
        '[style.top.px]': 'hostTopPx()',
        '[style.left.px]': 'hostLeftPx()',
        '[style.right]': 'hostRight()',
        '[style.width.px]': 'hostWidthPx()',
        '[style.height.px]': 'hostHeightPx()',
    },
})
export class FlowAssistantPanelComponent {
    @ViewChild('messagesContainer') messagesContainer?: ElementRef<HTMLDivElement>;
    @ViewChild('messageInput') messageInput?: ElementRef<HTMLTextAreaElement>;

    readonly assistantService = inject(FlowAssistantService);

    readonly showSettings = signal(false);
    readonly inputText = signal('');
    readonly sidebarOpen = signal<boolean>(this.loadPersistedSidebarOpen());
    readonly copiedMessageIndex = signal<number | null>(null);
    readonly kebabMenuOpen = signal(false);

    readonly messages = computed(() => this.assistantService.messages());
    readonly isStreaming = computed(() => this.assistantService.isStreaming());
    readonly mode = computed(() => this.assistantService.mode());
    readonly flowName = computed(() => this.assistantService.currentFlowName() ?? 'Flow Assistant');
    readonly isFullHeight = computed(() => this.assistantService.isFullHeight());
    readonly floatPosition = computed(() => this.assistantService.floatPosition());
    readonly floatSize = computed(() => this.assistantService.floatSize());
    readonly effectiveWidth = computed(() =>
        this.mode() === 'docked' ? this.assistantService.dockWidth() : this.floatSize().width
    );
    readonly sendDisabled = computed(() => this.isStreaming() || !this.inputText().trim());
    readonly currentStatus = computed(() => this.assistantService.currentStatus());
    readonly displayChips = computed(() => {
        const pending = this.assistantService.pendingPromptChips();
        return pending.length > 0 ? pending : this.assistantService.starterChips();
    });

    readonly liveToolsByAssistantIndex = computed<Map<number, ToolPillEntry[]>>(() => {
        const msgs = this.messages();
        const liveIds = this.assistantService.liveToolCallIds();
        const result = new Map<number, ToolPillEntry[]>();

        for (let i = 0; i < msgs.length; i++) {
            const msg = msgs[i];
            if (msg.role !== 'assistant') continue;

            const tools: ToolPillEntry[] = [];
            for (let j = i + 1; j < msgs.length; j++) {
                const next = msgs[j];
                if (next.role === 'user' || next.role === 'assistant') break;
                if (next.role === 'tool' && liveIds.has(next.tool_call_id)) {
                    const fakeEvent = {
                        type: 'tool_call' as const,
                        id: next.tool_call_id,
                        name: next.name,
                        arguments: next.arguments ?? {},
                    };
                    tools.push({
                        callId: next.tool_call_id,
                        name: next.name,
                        label: stripTrailingEllipsis(toolStatusFor(fakeEvent)),
                        args: next.arguments ?? {},
                        content: next.content,
                    });
                }
            }

            if (tools.length > 0) {
                result.set(i, tools);
            }
        }

        return result;
    });

    readonly kebabOverlayPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
    ];

    private readonly isAtBottom = signal(true);

    // 3. Computed — host binding values
    readonly isFloatingMode = computed(() => this.mode() === 'floating');
    readonly hostTopPx = computed(() => (this.mode() === 'floating' ? (this.floatPosition()?.y ?? null) : null));
    readonly hostLeftPx = computed(() => (this.mode() === 'floating' ? (this.floatPosition()?.x ?? null) : null));
    readonly hostRight = computed(() => (this.mode() === 'floating' ? 'auto' : null));
    readonly hostWidthPx = computed(() => this.effectiveWidth());
    readonly hostHeightPx = computed(() => (this.mode() === 'floating' ? this.floatSize().height : null));

    // 4. Effects
    private readonly scrollEffect = effect(() => {
        const msgs = this.messages();
        // Read last message content length so this effect re-fires on every streamed token.
        void (msgs.length > 0 ? ((msgs[msgs.length - 1] as { content?: string }).content?.length ?? 0) : 0);
        // Read status so the effect re-fires when the status line appears / disappears.
        void this.currentStatus();

        if (!this.isAtBottom()) return;

        // Schedule after the current rendering cycle so the DOM reflects the new content.
        requestAnimationFrame(() => {
            const container = this.messagesContainer?.nativeElement;
            if (container) {
                container.scrollTop = container.scrollHeight;
            }
        });
    });

    readonly resizeHandles: readonly ResizeDirection[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

    private isDragging: 'none' | 'docked-resize' | 'floating-move' | 'floating-resize' = 'none';
    private dragResizeDirection: ResizeDirection | null = null;
    private dragStartX = 0;
    private dragStartY = 0;
    private dragStartWidth = 0;
    private dragStartHeight = 0;
    private dragStartPositionX = 0;
    private dragStartPositionY = 0;

    isToolMessage(message: FlowAssistantMessage): message is {
        role: 'tool';
        content: string;
        tool_call_id: string;
        name: string;
        arguments?: Record<string, unknown>;
    } {
        return message.role === 'tool';
    }

    isAssistantMessage(message: FlowAssistantMessage): message is {
        role: 'assistant';
        content: string;
        ef_tables?: EfTable[];
        action_message?: ActionItem[];
        interrupted?: boolean;
    } {
        return message.role === 'assistant';
    }

    isUserMessage(message: FlowAssistantMessage): message is { role: 'user'; content: string } {
        return message.role === 'user';
    }

    isLastStreamingAssistant(message: FlowAssistantMessage, index: number): boolean {
        const msgs = this.messages();
        return this.isStreaming() && index === msgs.length - 1 && this.isAssistantMessage(message);
    }

    liveToolsForAssistant(index: number): ToolPillEntry[] | undefined {
        return this.liveToolsByAssistantIndex().get(index);
    }

    copyAssistantMessage(message: FlowAssistantMessage, index: number): void {
        if (!this.isAssistantMessage(message)) return;
        const text = message.content ?? '';
        if (!text) return;
        navigator.clipboard
            .writeText(text)
            .then(() => {
                this.copiedMessageIndex.set(index);
                setTimeout(() => {
                    if (this.copiedMessageIndex() === index) {
                        this.copiedMessageIndex.set(null);
                    }
                }, 1500);
            })
            .catch(() => {
                // Clipboard API can fail in non-secure contexts or denied permissions;
                // fail silently — the user can still drag-select + Ctrl+C.
            });
    }

    onActionExecuted(action: ActionItem): void {
        this.assistantService.executeAction(action);
    }

    toggleSettings(): void {
        this.showSettings.update((v) => !v);
    }

    toggleSidebar(): void {
        const next = !this.sidebarOpen();
        this.sidebarOpen.set(next);
        this.persistSidebarOpen(next);
    }

    closeSidebar(): void {
        if (!this.sidebarOpen()) return;
        this.sidebarOpen.set(false);
        this.persistSidebarOpen(false);
    }

    onChatBodyClick(): void {
        this.closeSidebar();
    }

    close(): void {
        this.assistantService.close();
    }

    onKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    sendMessage(): void {
        const text = this.inputText().trim();
        if (!text || this.sendDisabled()) return;

        this.assistantService.sendMessage(text);
        this.inputText.set('');
        this.autoResizeInput();
    }

    onInputChange(event: Event): void {
        const target = event.target as HTMLTextAreaElement;
        this.inputText.set(target.value);
        this.autoResizeInput();
    }

    onDragHandleMousedown(event: MouseEvent): void {
        event.preventDefault();
        this.isDragging = 'docked-resize';
        this.dragStartX = event.clientX;
        this.dragStartWidth = this.assistantService.dockWidth();
    }

    onHeaderMousedown(event: MouseEvent): void {
        if (this.mode() !== 'floating') return;
        const target = event.target as Element;
        if (target.closest('button') !== null) return;
        event.preventDefault();
        const position = this.floatPosition();
        this.isDragging = 'floating-move';
        this.dragStartX = event.clientX;
        this.dragStartY = event.clientY;
        this.dragStartPositionX = position?.x ?? 0;
        this.dragStartPositionY = position?.y ?? 0;
    }

    onFloatResizeHandleMousedown(event: MouseEvent, direction: ResizeDirection): void {
        event.preventDefault();
        event.stopPropagation();
        const size = this.floatSize();
        const position = this.floatPosition();
        this.dragResizeDirection = direction;
        this.isDragging = 'floating-resize';
        this.dragStartX = event.clientX;
        this.dragStartY = event.clientY;
        this.dragStartWidth = size.width;
        this.dragStartHeight = size.height;
        this.dragStartPositionX = position?.x ?? 0;
        this.dragStartPositionY = position?.y ?? 0;
    }

    onToggleMode(): void {
        this.assistantService.toggleMode();
    }

    onKebabClick(): void {
        this.kebabMenuOpen.update((v) => !v);
    }

    closeKebabMenu(): void {
        this.kebabMenuOpen.set(false);
    }

    onMenuItemClick(item: 'sessions' | 'settings' | 'clear-history' | 'reset-position'): void {
        this.closeKebabMenu();
        switch (item) {
            case 'sessions':
                this.toggleSidebar();
                break;
            case 'settings':
                this.toggleSettings();
                break;
            case 'clear-history':
                this.assistantService.clearChatHistory();
                break;
            case 'reset-position':
                this.assistantService.resetFloatPosition();
                break;
        }
    }

    onExpandClick(): void {
        this.assistantService.toggleFullHeight();
    }

    @HostListener('document:mousemove', ['$event'])
    onDocumentMousemove(event: MouseEvent): void {
        if (this.isDragging === 'none') return;

        if (this.isDragging === 'docked-resize') {
            const delta = this.dragStartX - event.clientX;
            const newWidth = Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, this.dragStartWidth + delta));
            this.assistantService.setDockWidth(newWidth);
            return;
        }

        if (this.isDragging === 'floating-move') {
            const dx = event.clientX - this.dragStartX;
            const dy = event.clientY - this.dragStartY;
            this.assistantService.setFloatPosition({
                x: this.dragStartPositionX + dx,
                y: this.dragStartPositionY + dy,
            });
            return;
        }

        if (this.isDragging === 'floating-resize') {
            const dir = this.dragResizeDirection;
            if (dir === null) return;
            const dx = event.clientX - this.dragStartX;
            const dy = event.clientY - this.dragStartY;

            let newWidth = this.dragStartWidth;
            let newHeight = this.dragStartHeight;
            let newX = this.dragStartPositionX;
            let newY = this.dragStartPositionY;

            if (dir.includes('e')) newWidth = this.dragStartWidth + dx;
            if (dir.includes('w')) newWidth = this.dragStartWidth - dx;
            if (dir.includes('s')) newHeight = this.dragStartHeight + dy;
            if (dir.includes('n')) newHeight = this.dragStartHeight - dy;

            // Pin size to min/max before computing the anchored position,
            // so dragging past the cap doesn't keep moving the panel.
            const clamped = this.assistantService.clampSize({ width: newWidth, height: newHeight });

            if (dir.includes('w')) newX = this.dragStartPositionX + (this.dragStartWidth - clamped.width);
            if (dir.includes('n')) newY = this.dragStartPositionY + (this.dragStartHeight - clamped.height);

            this.assistantService.setFloatBounds({ x: newX, y: newY }, clamped);
            return;
        }
    }

    @HostListener('document:mouseup')
    onDocumentMouseup(): void {
        this.isDragging = 'none';
        this.dragResizeDirection = null;
    }

    @HostListener('window:resize')
    onWindowResize(): void {
        if (this.mode() !== 'floating') return;
        // setFloatSize re-clamps position too, so a single call covers both.
        this.assistantService.setFloatSize(this.floatSize());
    }

    onMessagesScroll(): void {
        const container = this.messagesContainer?.nativeElement;
        if (!container) return;
        const atBottom =
            container.scrollTop + container.clientHeight >= container.scrollHeight - SCROLL_AT_BOTTOM_THRESHOLD;
        this.isAtBottom.set(atBottom);
    }

    trackByIndex(index: number): number {
        return index;
    }

    private loadPersistedSidebarOpen(): boolean {
        try {
            return localStorage.getItem(SIDEBAR_OPEN_KEY) === 'true';
        } catch {
            return false;
        }
    }

    private persistSidebarOpen(value: boolean): void {
        try {
            localStorage.setItem(SIDEBAR_OPEN_KEY, String(value));
        } catch {
            // Ignore storage errors
        }
    }

    private autoResizeInput(): void {
        const el = this.messageInput?.nativeElement;
        if (!el) return;
        el.style.height = 'auto';
        el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
}
