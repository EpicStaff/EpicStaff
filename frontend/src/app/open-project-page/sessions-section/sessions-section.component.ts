import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';

import { AppSvgIconComponent } from '../../shared/components/app-svg-icon/app-svg-icon.component';

interface Session {
    id: string;
    startTime: Date;
    endTime?: Date;
    status: 'active' | 'finished' | 'error';
}

@Component({
    selector: 'app-sessions-section',
    templateUrl: './sessions-section.component.html',
    styleUrls: ['./sessions-section.component.scss'],
    imports: [CommonModule, MatButtonModule, AppSvgIconComponent],
})
export class SessionsSectionComponent {
    selectedFilter: 'all' | 'active' | 'finished' | 'error' = 'all';

    // Mock data
    sessions: Session[] = [
        {
            id: '1',
            startTime: new Date(Date.now() - 3600000), // 1 hour ago
            status: 'active',
        },
        {
            id: '2',
            startTime: new Date(Date.now() - 7200000), // 2 hours ago
            endTime: new Date(Date.now() - 3600000),
            status: 'finished',
        },
        {
            id: '3',
            startTime: new Date(Date.now() - 10800000), // 3 hours ago
            endTime: new Date(Date.now() - 9000000),
            status: 'error',
        },
    ];

    get filteredSessions(): Session[] {
        if (this.selectedFilter === 'all') {
            return this.sessions;
        }
        return this.sessions.filter((session) => session.status === this.selectedFilter);
    }

    setFilter(filter: 'all' | 'active' | 'finished' | 'error') {
        this.selectedFilter = filter;
    }

    stopSession(sessionId: string) {
        // Implement stop session logic here
        console.log('Stopping session:', sessionId);
    }

    viewSession(sessionId: string) {
        // Implement view session logic here
        console.log('Viewing session:', sessionId);
    }

    formatDate(date: Date): string {
        return date.toLocaleString();
    }
}
