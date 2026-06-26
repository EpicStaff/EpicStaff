import { ChangeDetectionStrategy, Component, computed, inject, output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { FlowAssistantService } from '../../flow-assistant.service';
import { SessionSummary } from '../../models/flow-assistant.model';

function formatRelativeDate(isoString: string | null | undefined): string {
    if (!isoString) return '—';
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return '—';
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMinutes = Math.floor(diffMs / 60_000);
    const diffHours = Math.floor(diffMs / 3_600_000);
    const diffDays = Math.floor(diffMs / 86_400_000);

    if (diffMinutes < 1) return 'Just now';
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

@Component({
    selector: 'app-flow-assistant-sidebar',
    standalone: true,
    imports: [AppSvgIconComponent],
    templateUrl: './flow-assistant-sidebar.component.html',
    styleUrls: ['./flow-assistant-sidebar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantSidebarComponent {
    readonly selected = output<number>();

    readonly assistantService = inject(FlowAssistantService);

    readonly sessions = computed(() => this.assistantService.sessions());
    readonly currentConversationId = computed(() => this.assistantService.currentConversationId());

    formatDate(isoString: string | null | undefined): string {
        return formatRelativeDate(isoString);
    }

    sessionTitle(session: SessionSummary, index: number): string {
        return session.title ? session.title : `Session ${index + 1}`;
    }

    newSession(): void {
        this.assistantService.startNewSession();
    }

    selectSession(id: number): void {
        if (this.currentConversationId() === id) return;
        this.assistantService.selectSession(id);
        this.selected.emit(id);
    }

    deleteSession(event: MouseEvent, id: number): void {
        event.stopPropagation();
        this.assistantService.deleteSession(id);
    }

    trackById(_index: number, session: SessionSummary): number {
        return session.id;
    }
}
