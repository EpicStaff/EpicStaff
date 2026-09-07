import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, EventEmitter, inject, Input, Output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { RealtimeAgentDefinition } from '../../../../../features/agent-definitions/models/realtime-agent-definition.model';
import { ChatAgent, chatAgentTitle, sameChatAgent } from '../../../models/chat-agent.model';
import { ChatsService } from '../../../services/chats.service';
import { ConsoleService } from '../../../services/console.service';
import {
    AgentDefinitionRealtimeSettingsDialogComponent,
    AgentDefinitionRealtimeSettingsDialogData,
} from './agent-definition-realtime-settings-dialog/agent-definition-realtime-settings-dialog.component';

@Component({
    selector: 'app-chats-sidebar-item',
    imports: [MatTooltipModule],
    templateUrl: './chats-sidebar-item.component.html',
    styleUrls: ['./chats-sidebar-item.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsSidebarItemComponent {
    @Input({ required: true }) chatAgent!: ChatAgent;
    @Output() agentUpdated = new EventEmitter<ChatAgent>();

    private readonly chatsService = inject(ChatsService);
    private readonly consoleService = inject(ConsoleService);
    private readonly dialog = inject(Dialog);

    public readonly isSelected = computed(() => sameChatAgent(this.chatsService.selectedChatAgent$(), this.chatAgent));

    get title(): string {
        return chatAgentTitle(this.chatAgent);
    }

    public onSelect(): void {
        this.chatsService.setSelectedChatAgent(this.chatAgent);
        if (this.consoleService.isConversationConnected()) {
            this.consoleService.disconnectConversation();
        }
    }

    public openSettings(event: Event): void {
        event.stopPropagation();
        const { agent, realtime } = this.chatAgent;
        const data: AgentDefinitionRealtimeSettingsDialogData = {
            definitionId: agent.id,
            definitionName: agent.name,
            realtime,
        };
        const dialogRef = this.dialog.open<RealtimeAgentDefinition>(AgentDefinitionRealtimeSettingsDialogComponent, {
            data,
            width: '100%',
            maxWidth: '550px',
            height: '100%',
            maxHeight: '90vh',
        });

        dialogRef.closed.subscribe((updated) => {
            if (!updated) return;
            this.agentUpdated.emit({ agent: this.chatAgent.agent, realtime: updated });
        });
    }
}
