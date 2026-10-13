import { Component, effect, inject, untracked } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { HideInlineSubtitleOnOverflowDirective } from '@shared/directives';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { DeskRailComponent } from '../../components/desk-rail/desk-rail.component';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';

/**
 * The chat area's frame: the page header across the top, then the desk rail beside the routed page (All desks or one
 * desk). Moving between those pages swaps only the page, so the rail, its scroll position and the focus on its links
 * stay.
 */
@Component({
    selector: 'app-desks-shell',
    imports: [RouterOutlet, HideInlineSubtitleOnOverflowDirective, DeskRailComponent],
    templateUrl: './desks-shell.component.html',
    styleUrl: './desks-shell.component.scss',
})
export class DesksShellComponent {
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

    // The rail's badges: the same live counts as the sidenav badge.
    protected readonly waitingByDesk = inject(ChatInboxStreamService).waitingByBinding;

    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly myAliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly activeOrgService = inject(ActiveOrgService);
}
