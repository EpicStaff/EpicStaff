import { UserDeleteReport } from '@shared/models';

import {
    buildDeleteBreakdownItems,
    buildOrganizationDeleteMessage,
    buildUserDeleteMessage,
} from './delete-impact-message.util';

function userReport(affectedResources: Record<string, number>): UserDeleteReport {
    return { user_id: 7, affected_resources: affectedResources };
}

describe('buildOrganizationDeleteMessage', () => {
    it('warns that the organization will be permanently deleted', () => {
        expect(buildOrganizationDeleteMessage('Acme')).toBe(
            'You are about to permanently delete <strong>Acme</strong> organization. This action is irreversible.'
        );
    });
});

describe('buildDeleteBreakdownItems', () => {
    it('returns no items when nothing is affected', () => {
        expect(buildDeleteBreakdownItems({})).toEqual([]);
    });

    it('replaces underscores in resource names with spaces and capitalizes the first letter', () => {
        expect(buildDeleteBreakdownItems({ knowledge_documents: 2 })).toEqual([
            { label: 'Knowledge documents', count: 2 },
        ]);
    });

    it('sorts by count descending and breaks ties by name ascending', () => {
        expect(buildDeleteBreakdownItems({ tools: 2, agents: 5, labels: 2, crews: 9 })).toEqual([
            { label: 'Crews', count: 9 },
            { label: 'Agents', count: 5 },
            { label: 'Labels', count: 2 },
            { label: 'Tools', count: 2 },
        ]);
    });

    it('lists every resource without truncation', () => {
        const affectedResources = { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 };

        expect(buildDeleteBreakdownItems(affectedResources).map((item) => item.label)).toEqual([
            'G',
            'F',
            'E',
            'D',
            'C',
            'B',
            'A',
        ]);
    });
});

describe('buildUserDeleteMessage', () => {
    const OPENING = '<strong>Jane</strong> will be permanently deleted.';
    const CLOSING = ' Content they created in organizations is kept.';

    it('lists lost organizations and broken API keys when both apply', () => {
        expect(buildUserDeleteMessage('Jane', userReport({ memberships: 2, api_keys: 1 }))).toBe(
            `${OPENING} They will lose access to 2 organizations, and 1 API key will stop working.${CLOSING}`
        );
    });

    it('mentions only lost organizations when the user has no API keys', () => {
        expect(buildUserDeleteMessage('Jane', userReport({ memberships: 3 }))).toBe(
            `${OPENING} They will lose access to 3 organizations.${CLOSING}`
        );
    });

    it('mentions only broken API keys, capitalized, and omits the kept-content note when the user has no memberships', () => {
        expect(buildUserDeleteMessage('Jane', userReport({ api_keys: 3 }))).toBe(
            `${OPENING} 3 API keys will stop working.`
        );
    });

    it('uses the singular form for a count of one', () => {
        expect(buildUserDeleteMessage('Jane', userReport({ memberships: 1, api_keys: 1 }))).toBe(
            `${OPENING} They will lose access to 1 organization, and 1 API key will stop working.${CLOSING}`
        );
    });

    it('uses the singular form for a single API key without memberships', () => {
        expect(buildUserDeleteMessage('Jane', userReport({ api_keys: 1 }))).toBe(
            `${OPENING} 1 API key will stop working.`
        );
    });

    it('keeps only the opening sentence when the user has no memberships or API keys', () => {
        expect(buildUserDeleteMessage('Jane', userReport({}))).toBe(OPENING);
    });

    it('ignores every resource other than memberships and API keys', () => {
        const report = userReport({ tool_favorites: 5, avatar: 1, assistant_conversations: 9 });

        expect(buildUserDeleteMessage('Jane', report)).toBe(OPENING);
    });
});
