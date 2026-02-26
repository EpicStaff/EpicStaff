import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
  OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Dialog } from '@angular/cdk/dialog';
import { FullAgent } from '../../../../../../features/staff/services/full-agent.service';
import { ChatsService } from '../../../../services/chats.service';
import { ConsoleService } from '../../../../services/console.service';

import { TinyAudioVisualizerComponent } from '../chat-controls/frequency-circle/frequency-circle.component';
import { RealtimeSettingsDialogComponent } from '../../../chats-sidebar/chats-sidebar-item/realtime-settings-dialog/realtime-settings-dialog.component';

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

  showSettings = false;

  constructor(
    public chatsService: ChatsService,
    public consoleService: ConsoleService,
    private dialog: Dialog
  ) {}

  ngOnInit(): void {
    // No initialization needed for settings values anymore
  }

  get agent(): FullAgent | null {
    return this.chatsService.selectedAgent$();
  }

  toggleCommunicationType(type: 'audio' | 'text') {
    this.communicationType = type;
    this.communicationTypeChange.emit(type);
  }

  onVoiceChange(event: Event) {
    const select = event.target as HTMLSelectElement;
    this.voiceChange.emit(select.value);
  }

  openSettings(event: Event) {
    event.stopPropagation(); // Prevent any parent click events

    if (this.agent) {
      // Get the realtime agent for the selected agent
      //   const realtimeAgent = this.chatsService.getRealtimeAgentByAgentId(
      //     this.agent.id
      //   );

      this.dialog.open(RealtimeSettingsDialogComponent, {
        data: {
          agent: this.agent,
        },
        width: '100%',
      });
    }
  }

  // Keeping this method for backward compatibility if needed
  toggleSettings() {
    this.showSettings = !this.showSettings;
  }
}
