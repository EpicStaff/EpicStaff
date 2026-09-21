import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterModule } from '@angular/router';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { ChatsService } from '../../services/chats.service';
import { ConsoleService } from '../../services/console.service';
import { ChatComponent } from './chat/chat.component';

@Component({
    selector: 'app-chats-content',
    imports: [RouterModule, ChatComponent, HasPermissionDirective],
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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
