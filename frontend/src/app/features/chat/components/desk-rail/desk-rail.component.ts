import { BreakpointObserver } from '@angular/cdk/layout';
import { afterNextRender, Component, computed, DestroyRef, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { AppSvgIconComponent, FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { map } from 'rxjs';

import { BREAKPOINTS } from '../../../../core/constants/breakpoints';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ChatBindingActionsService } from '../../services/chat-binding-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { DeskRailModeService } from '../../services/desk-rail-mode.service';
import { bindingStatus, ChatBindingStatus } from '../../utils/binding-status.util';
import { deskBadgeText } from '../../utils/desk-avatar.util';
import { DeskAvatarComponent } from '../desk-avatar/desk-avatar.component';

const DESKS_ROUTE = '/chat-bindings';
const ALL_DESKS_NAME = 'All desks';
// The sidenav's Chat icon: All desks is where its badge leads.
const ALL_DESKS_ICON = 'message-circle';

type DeskListState = 'loading' | 'failed' | 'loaded';

interface DeskRailEntry {
    key: string;
    name: string;
    link: string[];
    /** Null for All desks: it is not a desk. */
    deskId: string | null;
    icon: string | null;
    status: ChatBindingStatus | null;
    count: number;
    badge: string | null;
}

/**
 * The chat area's leftmost column: All desks, one entry per desk and "+ New desk". Listed (avatar, name, badge) or
 * compact (avatars only, the name in a tooltip); the user's choice is remembered per browser, and narrow screens are
 * always compact. The entry of the current page is marked by the route.
 */
@Component({
    selector: 'app-desk-rail',
    imports: [
        RouterLink,
        RouterLinkActive,
        MatTooltipModule,
        AppSvgIconComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        DeskAvatarComponent,
    ],
    templateUrl: './desk-rail.component.html',
    styleUrl: './desk-rail.component.scss',
    host: {
        role: 'navigation',
        'aria-label': 'Desks',
        '[class.desk-rail--compact]': 'isCompact()',
    },
})
export class DeskRailComponent {
    /** People waiting per desk id (a desk with none may be absent); All desks shows their sum. */
    readonly waitingByDesk = input<Readonly<Record<string, number>>>({});

    protected readonly isNarrowScreen = toSignal(
        inject(BreakpointObserver)
            .observe(BREAKPOINTS.deskRailCompact)
            .pipe(map(({ matches }) => matches)),
        { initialValue: false }
    );
    /** Narrow screens force compact, whatever the user picked; the toggle is hidden meanwhile. */
    protected readonly isCompact = computed(() => this.isNarrowScreen() || this.railModeService.mode() === 'compact');
    protected readonly toggleLabel = computed(() => (this.isCompact() ? 'Show desk names' : 'Hide desk names'));
    protected readonly deskListState = computed((): DeskListState => {
        if (this.desksStorage.isLoaded()) return 'loaded';
        return this.desksStorage.loadFailed() ? 'failed' : 'loading';
    });
    /**
     * Read out by the status region. Empty until the rail has rendered once: a live region announces a change of its
     * text, not the text it was inserted with. Listed, a failure announces itself (the error state is an alert).
     */
    protected readonly statusMessage = computed(() => {
        if (!this.hasRendered()) return '';
        const state = this.deskListState();
        if (state === 'loading') return 'Loading desks…';
        return state === 'failed' && this.isCompact() ? "Couldn't load desks." : '';
    });
    /** Not before the list is known: an org that only looks empty would invite duplicate desks. */
    protected readonly canCreate = computed(
        () => this.deskListState() === 'loaded' && this.permissionsService.can(ResourceCode.Chats, ActionCode.Create)
    );
    protected readonly entries = computed((): DeskRailEntry[] => {
        const waiting = this.waitingByDesk();
        const total = Object.values(waiting).reduce((sum, count) => sum + count, 0);
        const allDesks: DeskRailEntry = {
            key: 'all',
            name: ALL_DESKS_NAME,
            link: [DESKS_ROUTE, 'all'],
            deskId: null,
            icon: ALL_DESKS_ICON,
            status: null,
            count: total,
            badge: deskBadgeText(total),
        };
        const desks = [...this.desksStorage.desks()]
            .sort((first, second) => first.name.localeCompare(second.name))
            .map((desk): DeskRailEntry => {
                const count = waiting[desk.id] ?? 0;
                return {
                    key: `desk:${desk.id}`,
                    name: desk.name,
                    link: [DESKS_ROUTE, desk.id],
                    deskId: desk.id,
                    icon: null,
                    status: bindingStatus(desk),
                    count,
                    badge: deskBadgeText(count),
                };
            });
        return [allDesks, ...desks];
    });
    private readonly hasRendered = signal(false);

    private readonly markRendered = afterNextRender(() => this.hasRendered.set(true));

    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly railModeService = inject(DeskRailModeService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly bindingActions = inject(ChatBindingActionsService);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);

    protected toggleMode(): void {
        this.railModeService.setMode(this.isCompact() ? 'list' : 'compact');
    }

    protected retryLoad(): void {
        this.desksStorage.reload();
    }

    /**
     * Opens the create dialog; a created desk opens at once. The desks reload on every close: Escape after a create
     * that showed an identity secret closes without the new desk.
     */
    protected createDesk(): void {
        this.bindingActions
            .create()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((created) => {
                this.desksStorage.reload();
                if (created) void this.router.navigate([DESKS_ROUTE, created.id]);
            });
    }
}
