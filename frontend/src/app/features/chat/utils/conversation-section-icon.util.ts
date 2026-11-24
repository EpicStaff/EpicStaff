import { ConversationListSection } from './conversation-list-tab.util';

/** How a section of the conversations column is drawn: its icon, the icon's box, and the icon's colour. */
export interface ConversationSectionIcon {
    icon: string;
    // The icon's box beside a section's label; each icon is sized to look as large as the others there. The badge has
    // its own, smaller one.
    size: string;
    // A CSS value.
    color: string;
}

/**
 * Each section's icon: on its header, on the avatar of every row it lists, so a row says which section it is in
 * wherever it scrolls to, and on the avatar in the open conversation's thread header.
 */
export const CONVERSATION_SECTION_ICONS: Readonly<Record<ConversationListSection, ConversationSectionIcon>> = {
    waiting: { icon: 'waiting', size: '12px', color: 'var(--color-status-waiting)' },
    in_progress: { icon: 'headset-outline', size: '12px', color: 'var(--color-status-in-progress)' },
    bot: { icon: 'bot', size: '14px', color: 'var(--accent-color)' },
    // Done, so muted.
    closed: { icon: 'closed', size: '12px', color: 'var(--color-text-secondary)' },
    test_open: { icon: 'flask', size: '12px', color: 'var(--color-status-info)' },
    test_closed: { icon: 'closed', size: '12px', color: 'var(--color-text-secondary)' },
};
