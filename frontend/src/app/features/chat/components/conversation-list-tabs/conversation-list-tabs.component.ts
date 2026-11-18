import { Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { ConversationListTab } from '../../utils/conversation-list-tab.util';

/**
 * The conversations column's first row: Inbox or Bot Testing, as two buttons of which one is pressed (the app's
 * segmented-switch pattern, as Mine and the audit filters use). It only says what the user picked; the column decides
 * what that lists.
 */
@Component({
    selector: 'app-conversation-list-tabs',
    imports: [AppSvgIconComponent, MatTooltipModule],
    templateUrl: './conversation-list-tabs.component.html',
    styleUrl: './conversation-list-tabs.component.scss',
})
export class ConversationListTabsComponent {
    readonly tab = input.required<ConversationListTab>();
    /** Waiting for a person, as Inbox's own header counts it; null shows none (while searching). */
    readonly inboxCount = input<number | null>(null);
    /** Bot Testing is for whoever builds desks: for anyone else it is there, but disabled, and says why. */
    readonly canTest = input(false);
    readonly tabChange = output<ConversationListTab>();

    protected select(tab: ConversationListTab): void {
        // Bot Testing stays focusable and clickable while disabled, so its tooltip can say why: a press does nothing.
        if (tab === 'testing' && !this.canTest()) return;
        if (tab !== this.tab()) this.tabChange.emit(tab);
    }
}
