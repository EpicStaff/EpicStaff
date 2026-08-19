import {
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    HostBinding,
    inject,
    Input,
    Output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SearchComponent } from '@shared/components';
import { ResizableSidebarDirective } from '@shared/directives';
import { SidebarWidthService } from '@shared/services';

import { ChatAgent, chatAgentTitle } from '../../models/chat-agent.model';
import { ChatsSidebarItemComponent } from './chats-sidebar-item/chats-sidebar-item.component';

const SIDEBAR_STORAGE_KEY = 'chats';

@Component({
    selector: 'app-chats-sidebar',
    imports: [ChatsSidebarItemComponent, FormsModule, SearchComponent, ResizableSidebarDirective],
    templateUrl: './chats-sidebar.component.html',
    styleUrls: ['./chats-sidebar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsSidebarComponent {
    @Input() agents: ChatAgent[] = [];
    @Output() agentUpdated = new EventEmitter<ChatAgent>();

    searchTerm = '';

    private readonly el = inject(ElementRef<HTMLElement>);
    private readonly sidebarWidthService = inject(SidebarWidthService);

    protected readonly sidebarStorageKey = SIDEBAR_STORAGE_KEY;
    protected readonly sidebarWidth = this.sidebarWidthService.getWidth(SIDEBAR_STORAGE_KEY);

    @HostBinding('style.width.px')
    get hostWidth(): number {
        return this.sidebarWidth();
    }

    protected get hostElement(): HTMLElement {
        return this.el.nativeElement;
    }

    trackByAgent(_index: number, agent: ChatAgent): string {
        return `${agent.kind}:${agent.agent.id}`;
    }

    get filteredAgents(): ChatAgent[] {
        const term = this.searchTerm.trim().toLowerCase();
        if (!term) return this.agents;
        return this.agents.filter((agent) => chatAgentTitle(agent).toLowerCase().includes(term));
    }
}
