import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, EventEmitter, inject, Input, Output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { RealtimeAgentDefinition } from '../../../../../features/agent-definitions/models/realtime-agent-definition.model';
import { FullAgent } from '../../../../../features/staff/services/full-agent.service';
import { ChatAgent, chatAgentTitle, sameChatAgent } from '../../../models/chat-agent.model';
import { ChatsService } from '../../../services/chats.service';
import { ConsoleService } from '../../../services/console.service';
import {
    AgentDefinitionRealtimeSettingsDialogComponent,
    AgentDefinitionRealtimeSettingsDialogData,
} from './agent-definition-realtime-settings-dialog/agent-definition-realtime-settings-dialog.component';
import { RealtimeSettingsDialogComponent } from './realtime-settings-dialog/realtime-settings-dialog.component';

@Component({
    selector: 'app-chats-sidebar-item',
    standalone: true,
    imports: [CommonModule, MatTooltipModule],
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
        if (this.chatAgent.kind === 'staff') {
            this.openStaffSettings(this.chatAgent.agent);
        } else {
            this.openDefinitionSettings(this.chatAgent.agent.id, this.chatAgent.agent.name, this.chatAgent.realtime);
        }
    }

    private openStaffSettings(agent: FullAgent): void {
        const dialogRef = this.dialog.open<FullAgent>(RealtimeSettingsDialogComponent, {
            data: { agent },
            width: '100%',
            maxWidth: '550px',
            height: '100%',
            maxHeight: '90vh',
        });

        dialogRef.closed.subscribe((updatedAgent) => {
            if (!updatedAgent) return;
            const merged: FullAgent = {
                ...updatedAgent,
                tools: agent.tools,
                python_code_tools: agent.python_code_tools,
            };
            this.agentUpdated.emit({ kind: 'staff', agent: merged });
        });
    }

    private openDefinitionSettings(
        definitionId: number,
        definitionName: string,
        realtime: RealtimeAgentDefinition
    ): void {
        const data: AgentDefinitionRealtimeSettingsDialogData = { definitionId, definitionName, realtime };
        const dialogRef = this.dialog.open<RealtimeAgentDefinition>(AgentDefinitionRealtimeSettingsDialogComponent, {
            data,
            width: '100%',
            maxWidth: '550px',
            height: '100%',
            maxHeight: '90vh',
        });

        dialogRef.closed.subscribe((updated) => {
            if (!updated || this.chatAgent.kind !== 'definition') return;
            this.agentUpdated.emit({ kind: 'definition', agent: this.chatAgent.agent, realtime: updated });
        });
    }
}
