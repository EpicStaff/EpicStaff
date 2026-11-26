import { Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { ConversationListSection } from '../../utils/conversation-list-tab.util';
import { sectionView } from '../../utils/conversation-section.util';
import { CONVERSATION_SECTION_ICONS } from '../../utils/conversation-section-icon.util';

// The section icon's box, the same for every section: smaller than a header's.
const BADGE_ICON_SIZE = '8px';

/**
 * A conversation's section on its avatar's corner: the section header's icon, in its colour, on a small disc whose
 * ring cuts it out of the avatar; its tooltip says who took the conversation, when someone did. It places itself on
 * the bottom-right corner of the nearest positioned box, 1px past it: the box sizes the avatar and leaves 4px for the
 * badge on its right. Hidden from assistive technology unless `isAnnounced`, where nothing else around it says its
 * section and holder.
 */
@Component({
    selector: 'app-conversation-section-badge',
    imports: [MatTooltipModule, AppSvgIconComponent],
    templateUrl: './conversation-section-badge.component.html',
    styleUrl: './conversation-section-badge.component.scss',
})
export class ConversationSectionBadgeComponent {
    readonly section = input.required<ConversationListSection>();
    /** Who holds the conversation ("you", a name); null while nobody does. */
    readonly holder = input<string | null>(null);
    /**
     * Whether assistive technology gets it: named by its section, its tooltip describing the holder, and focusable
     * for that tooltip when it has one. Off where its host already says both (a row's accessible name).
     */
    readonly isAnnounced = input(false);

    protected readonly icon = computed(() => CONVERSATION_SECTION_ICONS[this.section()]);
    /** None while nobody holds it. */
    protected readonly takenByNote = computed(() => {
        const holder = this.holder();
        return holder ? `Taken by ${holder}` : '';
    });
    protected readonly sectionLabel = computed(() => sectionView(this.section()).label);
    protected readonly iconSize = BADGE_ICON_SIZE;
}
