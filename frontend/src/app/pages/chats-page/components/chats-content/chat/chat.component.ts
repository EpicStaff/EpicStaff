// chat.component.ts
import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChatsService } from '../../../services/chats.service';
import { ChatControlsComponent } from './chat-controls/chat-controls.component';
import { ChatHeaderComponent } from './chat-header/chat-header.component';
import { ChatMessagesComponent } from './chat-messages/chat-messages.component';

@Component({
    selector: 'app-chat',
    standalone: true,
    imports: [CommonModule, FormsModule, ChatMessagesComponent, ChatHeaderComponent, ChatControlsComponent],
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.scss'],
})
export class ChatComponent {
    constructor(public chatsService: ChatsService) {}

    get hasSelection(): boolean {
        return this.chatsService.selectedChatAgent$() !== null;
    }
}
