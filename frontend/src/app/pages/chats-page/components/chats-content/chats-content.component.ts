import { NgIf } from '@angular/common';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterModule } from '@angular/router';

import { ChatsService } from '../../services/chats.service';
import { ConsoleService } from '../../services/console.service';
import { ChatComponent } from './chat/chat.component';

@Component({
    selector: 'app-chats-content',
    standalone: true,
    imports: [NgIf, RouterModule, ChatComponent],
    templateUrl: './chats-content.component.html',
    styleUrls: ['./chats-content.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsContentComponent {
    constructor(
        public consoleService: ConsoleService,
        public chatsService: ChatsService
    ) {}

    public get hasSelection(): boolean {
        return this.chatsService.selectedChatAgent$() !== null;
    }

    // Empty-state CTA points to where you actually create/configure the missing kind.
    public get isAgentsTab(): boolean {
        return this.chatsService.activeTab() === 'definition';
    }

    public get emptyCtaLink(): string {
        return '/agents';
    }

    public get emptyCtaLabel(): string {
        return 'Go to Agents';
    }

    ngOnDestroy() {}
}
