import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuditSessionEvent } from './models/audit-session.models';
import { AuditApiService } from './services/audit-api.service';
import { groupAuditSessions } from './utils/group-audit-sessions.util';

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

@Component({
    selector: 'app-audit-sessions-browser',
    standalone: true,
    imports: [CommonModule, RouterLink],
    templateUrl: './audit-sessions-browser.component.html',
    styleUrls: ['./audit-sessions-browser.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditSessionsBrowserComponent implements OnInit {
    private auditApiService = inject(AuditApiService);
    public readonly timeZoneLabel = buildTimeZoneLabel();

    public isLoading = signal<boolean>(false);
    public loadError = signal<boolean>(false);
    public isPartial = signal<boolean>(false);
    public pageSize = signal<number>(20);
    public areColumnsExpanded = signal<boolean>(false);
    private rawEvents = signal<AuditSessionEvent[]>([]);
    private cursorStack = signal<(string | null)[]>([null]);
    private nextCursor = signal<string | null>(null);

    public rows = computed(() => groupAuditSessions(this.rawEvents()));
    public canGoNewer = computed(() => this.cursorStack().length > 1);
    public canGoOlder = computed(() => this.nextCursor() !== null);

    public counts = computed(() => {
        const events = this.rawEvents();
        return {
            sessions: events.filter((event) => event.kind === 'session').length,
            nodes: events.filter((event) => event.kind === 'node').length,
            events: events.filter((event) => event.kind === 'event').length,
        };
    });

    public canDecreasePageSize = computed(() => PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) > 0);
    public canIncreasePageSize = computed(
        () => PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) < PAGE_SIZE_OPTIONS.length - 1
    );

    public ngOnInit(): void {
        this.loadSessions();
    }

    public stepPageSize(delta: number): void {
        const next = PAGE_SIZE_OPTIONS[PAGE_SIZE_OPTIONS.indexOf(this.pageSize()) + delta];
        if (next === undefined) {
            return;
        }
        this.pageSize.set(next);
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public goToFirstPage(): void {
        if (!this.canGoNewer()) {
            return;
        }
        this.cursorStack.set([null]);
        this.loadSessions();
    }

    public goToNewerPage(): void {
        if (!this.canGoNewer()) {
            return;
        }
        this.cursorStack.update((stack) => stack.slice(0, -1));
        this.loadSessions();
    }

    public goToOlderPage(): void {
        const cursor = this.nextCursor();
        if (cursor === null) {
            return;
        }
        this.cursorStack.update((stack) => [...stack, cursor]);
        this.loadSessions();
    }

    public setColumnsExpanded(expanded: boolean): void {
        this.areColumnsExpanded.set(expanded);
    }

    public loadSessions(): void {
        const stack = this.cursorStack();
        this.isLoading.set(true);
        this.loadError.set(false);

        this.auditApiService
            .searchSessions({
                filters: { field: 'kind', op: 'in', value: ['session'] },
                match_scope: { children: true },
                cursor: stack[stack.length - 1],
                size: this.pageSize(),
            })
            .subscribe({
                next: (response) => {
                    this.rawEvents.set(response.items);
                    this.nextCursor.set(response.next_cursor);
                    this.isPartial.set(response.partial);
                    this.isLoading.set(false);
                },
                error: () => {
                    this.rawEvents.set([]);
                    this.nextCursor.set(null);
                    this.isPartial.set(false);
                    this.loadError.set(true);
                    this.isLoading.set(false);
                },
            });
    }
}

function buildTimeZoneLabel(): string {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offsetMinutes = -new Date().getTimezoneOffset();
    const sign = offsetMinutes < 0 ? '-' : '+';
    const absolute = Math.abs(offsetMinutes);
    const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
    const minutes = String(absolute % 60).padStart(2, '0');
    return `${sign}${hours}:${minutes} ${zone}`;
}
