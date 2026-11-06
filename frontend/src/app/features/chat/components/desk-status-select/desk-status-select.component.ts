import { CdkMenu, CdkMenuItemRadio, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { TabThroughMenuDirective } from '@shared/directives';

import { ChatBinding } from '../../models/chat.model';
import { bindingStatus, CHAT_BINDING_STATUS_LABELS, ChatBindingStatus } from '../../utils/binding-status.util';

/** What the operator can set a desk to: taking it live (resume) or pausing it. */
export type DeskRunState = 'live' | 'paused';

interface DeskRunStateOption {
    value: DeskRunState;
    label: string;
    description: string;
    dotColor: string;
}

const STATUS_DOT_COLORS: Record<ChatBindingStatus, string> = {
    live: 'var(--success-color)',
    paused: 'var(--color-status-paused)',
    broken: 'var(--color-status-failed)',
};

const RUN_STATE_OPTIONS: readonly DeskRunStateOption[] = [
    { value: 'live', label: 'Live', description: 'Visitors can chat', dotColor: STATUS_DOT_COLORS.live },
    {
        value: 'paused',
        label: 'Pause',
        description: 'Inbox paused. Test lab active.',
        dotColor: STATUS_DOT_COLORS.paused,
    },
];

/**
 * A desk's status in its toolbar, a dot and a word, with a menu that takes the desk live or pauses it. Without the
 * right to change it, only the status is shown. A broken desk says why on hover and keyboard focus.
 */
@Component({
    selector: 'app-desk-status-select',
    imports: [
        NgTemplateOutlet,
        MatTooltipModule,
        AppSvgIconComponent,
        CdkMenuTrigger,
        CdkMenu,
        CdkMenuItemRadio,
        TabThroughMenuDirective,
    ],
    templateUrl: './desk-status-select.component.html',
    styleUrl: './desk-status-select.component.scss',
})
export class DeskStatusSelectComponent {
    readonly binding = input.required<ChatBinding>();
    readonly canChange = input(false);
    /** A state other than the current one was picked. */
    readonly runStateChange = output<DeskRunState>();

    protected readonly status = computed(() => bindingStatus(this.binding()));
    protected readonly label = computed(() => CHAT_BINDING_STATUS_LABELS[this.status()]);
    protected readonly dotColor = computed(() => STATUS_DOT_COLORS[this.status()]);
    protected readonly currentRunState = computed((): DeskRunState => (this.binding().is_active ? 'live' : 'paused'));
    // What the operator has to fix; null unless broken.
    protected readonly brokenReason = computed(() => this.binding().broken_reason || null);
    protected readonly triggerLabel = computed(() => `Desk status: ${this.label()}. Change`);

    protected readonly options = RUN_STATE_OPTIONS;
    // Below the trigger, left edges aligned; flips above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
    ];

    protected pick(value: DeskRunState): void {
        if (value !== this.currentRunState()) this.runStateChange.emit(value);
    }
}
