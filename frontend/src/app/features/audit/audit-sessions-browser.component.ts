import { CommonModule } from '@angular/common';
import { Component, inject, OnInit, signal } from '@angular/core';

import { AuditSessionEvent } from './models/audit-session.models';
import { AuditApiService } from './services/audit-api.service';

@Component({
    selector: 'app-audit-sessions-browser',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './audit-sessions-browser.component.html',
    styleUrls: ['./audit-sessions-browser.component.scss'],
})
export class AuditSessionsBrowserComponent implements OnInit {
    private auditApiService = inject(AuditApiService);

    public sessions = signal<AuditSessionEvent[]>([]);
    public isLoading = signal<boolean>(false);

    public ngOnInit(): void {
        this.loadSessions();
    }

    public loadSessions(): void {
        this.isLoading.set(true);
        this.auditApiService
            .searchSessions({
                filters: { field: 'kind', op: 'in', value: ['session', 'node', 'event'] },
                size: 20,
            })
            .subscribe({
                next: (response) => {
                    this.sessions.set(response.items);
                    this.isLoading.set(false);
                },
                error: () => {
                    this.isLoading.set(false);
                },
            });
    }
}
