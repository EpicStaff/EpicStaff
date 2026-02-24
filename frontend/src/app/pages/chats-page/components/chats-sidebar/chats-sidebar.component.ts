import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { AsyncPipe, NgFor } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ChatsSidebarItemComponent } from './chats-sidebar-item/chats-sidebar-item.component';
import { ChatsService } from '../../services/chats.service';
import { FullAgent } from '@services';
import { SearchComponent } from "@shared/components";

@Component({
  selector: 'app-chats-sidebar',
  standalone: true,
  imports: [NgFor, ChatsSidebarItemComponent, FormsModule, SearchComponent],
  templateUrl: './chats-sidebar.component.html',
  styleUrls: ['./chats-sidebar.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatsSidebarComponent {
  @Input() agents: FullAgent[] = [];
  searchRole: string = '';

  constructor(private chatsService: ChatsService) {}

  get selectedAgentId() {
    return this.chatsService.selectedAgentId$;
  }

  trackByAgentId(index: number, agent: FullAgent): number {
    return agent.id as number;
  }

  get filteredAgents(): FullAgent[] {
    if (!this.searchRole.trim()) {
      return this.agents;
    }

    return this.agents.filter((agent) =>
      agent.role?.toLowerCase().includes(this.searchRole.toLowerCase())
    );
  }
}
