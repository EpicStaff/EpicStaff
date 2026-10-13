import { Dialog } from '@angular/cdk/dialog';
import { CdkMenu, CdkMenuItem, CdkMenuTrigger } from '@angular/cdk/menu';
import { ConnectedPosition } from '@angular/cdk/overlay';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AuthorshipDetailsDialogService,
    ButtonComponent,
    ConfirmationDialogService,
    FetchErrorStateComponent,
    LoadingSpinnerComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, RealtimeChannel, ResourceCode } from '@shared/models';
import { RealtimeChannelService } from '@shared/services';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { AgentDefinition } from '../../../agent-definitions/models/agent-definition.model';
import { AgentDefinitionsApiService } from '../../../agent-definitions/services/agent-definitions-api.service';
import {
    AddEditChannelDialogComponent,
    AddEditChannelDialogData,
} from './add-edit-channel-dialog/add-edit-channel-dialog.component';

@Component({
    selector: 'app-voice-settings-tab',
    templateUrl: './voice-settings-section.component.html',
    styleUrls: ['./voice-settings-section.component.scss'],
    imports: [
        ButtonComponent,
        LoadingSpinnerComponent,
        HasPermissionDirective,
        FetchErrorStateComponent,
        CdkMenuTrigger,
        CdkMenu,
        CdkMenuItem,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoiceSettingsSectionComponent implements OnInit {
    private channelService = inject(RealtimeChannelService);
    private agentDefinitionsApi = inject(AgentDefinitionsApiService);
    private dialog = inject(Dialog);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private readonly authorshipDetailsDialog = inject(AuthorshipDetailsDialogService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    status = signal<LoadingState>(LoadingState.IDLE);

    channels = signal<RealtimeChannel[]>([]);
    private agentDefinitions = signal<AgentDefinition[]>([]);

    agentDefinitionMap = computed<Map<number, string>>(
        () => new Map(this.agentDefinitions().map((d) => [d.id, d.name]))
    );

    // Below the ⋮ button, right edges aligned; flips above when there is no room.
    protected readonly menuPositions: ConnectedPosition[] = [
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    ngOnInit(): void {
        this.loadAll();

        this.channelService.channelsChanged$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshChannels());
    }

    retry(): void {
        this.loadAll();
    }

    private loadAll(): void {
        this.status.set(LoadingState.LOADING);

        this.channelService
            .getChannels()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (channels) => {
                    this.channels.set(channels);
                    this.status.set(LoadingState.LOADED);
                },
                error: () => this.status.set(LoadingState.ERROR),
            });

        this.agentDefinitionsApi
            .getAgentDefinitions()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ next: (defs) => this.agentDefinitions.set(defs), error: () => {} });
    }

    getStreamUrl(channel: RealtimeChannel): string | null {
        const liveUrl = channel.twilio?.webhook_trigger?.live_url;
        if (!liveUrl) return null;
        const base = liveUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
        return `wss://${base}/voice/${channel.token}/stream`;
    }

    onAddChannel(): void {
        const ref = this.dialog.open<boolean, AddEditChannelDialogData>(AddEditChannelDialogComponent, {
            disableClose: true,
            data: { channel: null, action: 'create' },
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((saved) => {
            if (saved) this.refreshChannels();
        });
    }

    onEditChannel(channel: RealtimeChannel): void {
        const ref = this.dialog.open<boolean, AddEditChannelDialogData>(AddEditChannelDialogComponent, {
            disableClose: true,
            data: { channel, action: 'update' },
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((saved) => {
            if (saved) this.refreshChannels();
        });
    }

    /**
     * The menu item closes the menu itself once this returns, focusing its trigger; the details
     * dialog has already recorded the focused menu item by then, so it is told to close back to
     * the ⋮ button instead.
     */
    protected onViewDetails(channel: RealtimeChannel, menuTriggerButton: HTMLElement): void {
        this.authorshipDetailsDialog.open('Channel Details', channel, menuTriggerButton);
    }

    /**
     * Escape must close only the menu, not the Configure Models dialog under it: CdkMenu lets
     * Escape bubble on to the overlay keyboard dispatcher after destroying the menu view, so the
     * focused item intercepts it first and closes the menu the way CdkMenu would.
     */
    protected onMenuItemEscape(event: Event, menuTrigger: CdkMenuTrigger, menuTriggerButton: HTMLElement): void {
        event.stopPropagation();
        menuTrigger.close();
        menuTriggerButton.focus();
    }

    onDeleteChannel(channel: RealtimeChannel): void {
        this.confirmationDialogService
            .confirmDelete(channel.name)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.channelService
                        .deleteChannel(channel.id)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: () => {
                                this.channels.update((chs) => chs.filter((c) => c.id !== channel.id));
                                this.toastService.success(`Channel "${channel.name}" deleted`);
                            },
                            error: () => this.toastService.error('Failed to delete channel'),
                        });
                }
            });
    }

    private refreshChannels(): void {
        this.channelService
            .getChannels()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ next: (channels) => this.channels.set(channels), error: () => {} });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
