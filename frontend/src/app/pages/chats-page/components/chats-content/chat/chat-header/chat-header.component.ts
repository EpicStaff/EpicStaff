import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChatAgentVM } from '../../../../models/chat-agent.model';
import { ChatsService } from '../../../../services/chats.service';
import { ConsoleService } from '../../../../services/console.service';
import { TinyAudioVisualizerComponent } from '../chat-controls/frequency-circle/frequency-circle.component';

@Component({
    selector: 'app-chat-header',
    standalone: true,
    imports: [CommonModule, FormsModule, TinyAudioVisualizerComponent],
    templateUrl: './chat-header.component.html',
    styleUrls: ['./chat-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatHeaderComponent implements OnInit {
    @Input() communicationType: 'audio' | 'text' = 'audio';
    @Input() selectedVoice: string = 'Jake';
    @Input() voices: string[] = ['Jake', 'Lucio', 'Mark'];

    @Output() communicationTypeChange = new EventEmitter<'audio' | 'text'>();
    @Output() voiceChange = new EventEmitter<string>();

    constructor(
        public chatsService: ChatsService,
        public consoleService: ConsoleService
    ) {}

    ngOnInit(): void {
        // No initialization needed for settings values anymore
    }

    get vm(): ChatAgentVM | null {
        return this.chatsService.selectedAgentVM$();
    }

    toggleCommunicationType(type: 'audio' | 'text') {
        this.communicationType = type;
        this.communicationTypeChange.emit(type);
    }

    onVoiceChange(event: Event) {
        const select = event.target as HTMLSelectElement;
        this.voiceChange.emit(select.value);
    }
}
