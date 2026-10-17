import { CdkTrapFocus } from '@angular/cdk/a11y';
import { afterNextRender, Component, computed, effect, inject, Injector, untracked, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';
import { urlPath } from '@shared/utils';
import { filter } from 'rxjs';

import { AppNavigationDrawerService } from '../../../../core/services/app-navigation-drawer.service';
import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { DeskRailComponent } from '../../components/desk-rail/desk-rail.component';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { DeskDrawerService } from '../../services/desk-drawer.service';

/**
 * The chat area's frame: the page header across the top, then the desk rail beside the routed page (All desks or one
 * desk). Moving between those pages swaps only the page, so the rail, its scroll position and the focus on its links
 * stay. On phones the page takes the whole screen: the header keeps only its heading, for screen readers, and the rail
 * moves into a drawer that the page's desk switcher opens (through `DeskDrawerService`, provided here so that the
 * routed page reaches the drawer of the shell it is in).
 */
@Component({
    selector: 'app-desks-shell',
    imports: [
        RouterOutlet,
        CdkTrapFocus,
        AppSvgIconComponent,
        HideInlineSubtitleOnOverflowDirective,
        DeskRailComponent,
    ],
    providers: [DeskDrawerService],
    templateUrl: './desks-shell.component.html',
    styleUrl: './desks-shell.component.scss',
})
export class DesksShellComponent {
    private readonly drawerTrap = viewChild(CdkTrapFocus);

    protected readonly isPhone = inject(PhoneLayoutService).isPhone;
    protected readonly isDrawerShown = computed(() => this.isPhone() && this.deskDrawer.isOpen());

    /**
     * The desks, and the names the user goes by on them, load when the chat area opens, again on every stream `ready`
     * (a reconnect may have missed changes) and for a newly active org; the org switch has already cleared the
     * previous org's. Without an org (a logout) the storages ask for nothing.
     */
    private readonly reloadDesks = effect(() => {
        this.chatInboxStream.readyEpoch();
        this.activeOrgService.activeOrgId();
        untracked(() => {
            this.desksStorage.reload();
            this.myAliasesStorage.reload();
        });
    });
    // A wider screen shows the rail itself: nothing stays open, unseen, behind it.
    private readonly closeDrawerOffPhones = effect(() => {
        if (!this.isPhone()) untracked(() => this.deskDrawer.close({ restoreFocus: false }));
    });
    // The drawer is a modal dialog: the focus goes in when it opens and stays there until it closes. No scrolling to
    // it: the drawer is still sliding in from past the edge.
    private readonly focusOpenedDrawer = effect(() => {
        const trap = this.drawerTrap();
        if (!trap) return;
        untracked(() =>
            afterNextRender(() => trap.focusTrap.focusInitialElement({ preventScroll: true }), {
                injector: this.injector,
            })
        );
    });

    // The rail's badges: the same live counts as the sidenav badge.
    protected readonly waitingByDesk = inject(ChatInboxStreamService).waitingByBinding;
    protected readonly deskDrawer = inject(DeskDrawerService);

    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly myAliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly appNavigation = inject(AppNavigationDrawerService);
    private readonly injector = inject(Injector);

    constructor() {
        // A pick in the drawer closes it (whatever its navigation changes: a query only, or nothing). So does a move to
        // another page made elsewhere (a deleted desk sends the page to All desks); a navigation that changes only the
        // query is the page's own (the open conversation) and leaves the drawer be.
        const router = inject(Router);
        let shownPath = urlPath(router.url);
        router.events
            .pipe(
                filter((event): event is NavigationEnd => event instanceof NavigationEnd),
                takeUntilDestroyed()
            )
            .subscribe((event) => {
                const path = urlPath(event.urlAfterRedirects);
                if (path !== shownPath) this.deskDrawer.close();
                shownPath = path;
            });
    }

    /** From the drawer to the app navigation, which hands the focus back to the desk switcher when it closes. */
    protected openAppMenu(): void {
        const switcher = this.deskDrawer.opener;
        this.deskDrawer.close({ restoreFocus: false });
        this.appNavigation.open(switcher);
    }
}
