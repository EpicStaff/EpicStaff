import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';

import { GraphSessionLight } from '../../../../features/flows/services/flows-sessions.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-session-id-switcher',
    imports: [FormsModule, MatTooltipModule, AppSvgIconComponent],
    templateUrl: './session-id-switcher.component.html',
    styleUrls: ['./session-id-switcher.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SessionIdSwitcherComponent {
    @Input() sessions: GraphSessionLight[] = [];
    @Input() selectedSessionId: string | null = null;
    @Output() sessionSelected = new EventEmitter<string>();

    public searchQuery = '';
    public isDropdownOpen = false;

    public onSessionChange(sessionId: string): void {
        this.isDropdownOpen = false;
        this.searchQuery = '';
        this.sessionSelected.emit(sessionId);
    }

    public toggleDropdown(): void {
        this.isDropdownOpen = !this.isDropdownOpen;
        if (!this.isDropdownOpen) {
            this.searchQuery = '';
        }
    }

    public closeDropdown(): void {
        this.isDropdownOpen = false;
        this.searchQuery = '';
    }

    public get filteredSessions(): GraphSessionLight[] {
        if (!this.searchQuery) return this.sessions;
        return this.sessions.filter((s) => s.id.toString().includes(this.searchQuery));
    }

    public get selectedSessionLabel(): string {
        const session = this.sessions.find((s) => s.id.toString() === this.selectedSessionId);
        return session ? `ID ${session.id}` : `ID -`;
    }

    // `sessions` is sorted newest-first, so the previous (older) session is the next index down the list.
    public goToPreviousSession(): void {
        const index = this.getCurrentSessionIndex();
        if (index >= 0 && index < this.sessions.length - 1) {
            this.onSessionChange(this.sessions[index + 1].id.toString());
        }
    }

    public goToNextSession(): void {
        const index = this.getCurrentSessionIndex();
        if (index > 0) {
            this.onSessionChange(this.sessions[index - 1].id.toString());
        }
    }

    public get hasPreviousSession(): boolean {
        const index = this.getCurrentSessionIndex();
        return index >= 0 && index < this.sessions.length - 1;
    }

    public get hasNextSession(): boolean {
        return this.getCurrentSessionIndex() > 0;
    }

    public getTimeAgo(dateStr: string): string {
        const now = Date.now();
        const diff = now - new Date(dateStr).getTime();
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        const weeks = Math.floor(days / 7);
        const months = Math.floor(days / 30);

        if (seconds < 60) return 'just now';
        if (minutes < 60) return `${minutes} min ago`;
        if (hours < 24) return `${hours}h ago`;
        if (days < 7) return `${days}d ago`;
        if (weeks < 5) return `${weeks}w ago`;
        return `${months}mo ago`;
    }

    private getCurrentSessionIndex(): number {
        if (!this.selectedSessionId) return -1;
        return this.sessions.findIndex((s) => s.id.toString() === this.selectedSessionId);
    }
}
