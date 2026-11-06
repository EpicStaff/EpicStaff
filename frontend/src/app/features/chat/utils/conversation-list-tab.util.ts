import { ChatConversation, ChatInboxSection } from '../models/chat.model';

/**
 * The conversations column's two tabs: Inbox (the work: Waiting, In progress, Closed, Bot) and Bot Testing (the test
 * conversations desk builders start). A conversation is in exactly one of them, for good: a test stays a test.
 */
export type ConversationListTab = 'inbox' | 'testing';

/** Inbox's sections: one server list each. */
export type InboxSection = Exclude<ChatInboxSection, 'test'>;

/**
 * Bot Testing's sections: the server's one `test` list, split in the column into the tests still open and the closed
 * ones.
 */
export type TestingSection = 'test_bot' | 'test_closed';

/** A section the column shows, under its own header. */
export type ConversationListSection = InboxSection | TestingSection;

export const isTestingSection = (section: ConversationListSection): section is TestingSection =>
    section === 'test_bot' || section === 'test_closed';

export const tabOfSection = (section: ConversationListSection): ConversationListTab =>
    isTestingSection(section) ? 'testing' : 'inbox';

export const tabOfConversation = (conversation: ChatConversation): ConversationListTab =>
    conversation.is_test ? 'testing' : 'inbox';
