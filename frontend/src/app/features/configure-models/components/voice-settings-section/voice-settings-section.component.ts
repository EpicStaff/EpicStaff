import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService, LoadingSpinnerComponent } from '@shared/components';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { ToastService } from '../../../../services/notifications';
import { RealtimeChannel } from '../../../../shared/models/realtime-voice/realtime-channel.model';
import { RealtimeChannelService } from '../../../../shared/services/realtime-channel.service';
import { GetAgentRequest } from '../../../staff/models/agent.model';
import { AgentsService } from '../../../staff/services/staff.service';
import {
    AddEditChannelDialogComponent,
    AddEditChannelDialogData,
} from './add-edit-channel-dialog/add-edit-channel-dialog.component';

@Component({
    selector: 'app-voice-settings-tab',
    templateUrl: './voice-settings-section.component.html',
    styleUrls: ['./voice-settings-section.component.scss'],
    imports: [ButtonComponent, LoadingSpinnerComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoiceSettingsSectionComponent implements OnInit {
    private channelService = inject(RealtimeChannelService);
    private agentsService = inject(AgentsService);
    private dialog = inject(Dialog);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    status = signal<LoadingState>(LoadingState.IDLE);

    channels = signal<RealtimeChannel[]>([]);
    private agents = signal<GetAgentRequest[]>([]);

    agentMap = computed<Map<number, string>>(() => new Map(this.agents().map((a) => [a.id, a.role])));

    ngOnInit(): void {
        this.loadAll();

        this.channelService.channelsChanged$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refreshChannels());
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

        this.agentsService
            .getAgentsWithRealtimeConfig()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ next: (agents) => this.agents.set(agents), error: () => {} });
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
}
