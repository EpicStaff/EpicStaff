import { OrganizationDeleteReport, UserDeleteReport } from '@shared/models';

import { buildOrganizationDeleteMessage, buildUserDeleteMessage } from './delete-impact-message.util';

function organizationReport(affectedResources: Record<string, number>): OrganizationDeleteReport {
    return { organization_id: 3, affected_resources: affectedResources };
}

function userReport(affectedResources: Record<string, number>): UserDeleteReport {
    return { user_id: 7, affected_resources: affectedResources };
}

describe('buildOrganizationDeleteMessage', () => {
    function expectedMessage(name: string, impact: string): string {
        return `<strong>${name}</strong> and everything it owns will be permanently deleted: ${impact}.`;
    }

    it('reports no additional data when nothing else is affected', () => {
        expect(buildOrganizationDeleteMessage('Acme', organizationReport({}))).toBe(
            expectedMessage('Acme', 'no additional data')
        );
    });

    it('lists a single resource with its total', () => {
        expect(buildOrganizationDeleteMessage('Acme', organizationReport({ agents: 1 }))).toBe(
            expectedMessage('Acme', '1 agents (1 items total)')
        );
    });

    it('replaces underscores in resource names with spaces', () => {
        expect(buildOrganizationDeleteMessage('Acme', organizationReport({ knowledge_documents: 2 }))).toBe(
            expectedMessage('Acme', '2 knowledge documents (2 items total)')
        );
    });

    it('sorts by count descending and breaks ties by name ascending', () => {
        const report = organizationReport({ tools: 2, agents: 5, labels: 2, crews: 9 });

        expect(buildOrganizationDeleteMessage('Acme', report)).toBe(
            expectedMessage('Acme', '9 crews, 5 agents, 2 labels, 2 tools (18 items total)')
        );
    });

    it('shows the top five resources, marks the rest as more and totals every resource', () => {
        const report = organizationReport({ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 });

        expect(buildOrganizationDeleteMessage('Acme', report)).toBe(
            expectedMessage('Acme', '7 g, 6 f, 5 e, 4 d, 3 c, and more (28 items total)')
        );
    });

    it('does not mark more when there are exactly five resources', () => {
        const report = organizationReport({ a: 1, b: 1, c: 1, d: 1, e: 1 });

        expect(buildOrganizationDeleteMessage('Acme', report)).toBe(
            expectedMessage('Acme', '1 a, 1 b, 1 c, 1 d, 1 e (5 items total)')
        );
    });

    it('describes a realistic organization deletion including stored files', () => {
        const report = organizationReport({
            flow: 4,
            agents: 6,
            sessions: 20,
            knowledge_documents: 12,
            storage_files: 12,
            memberships: 3,
            secrets: 1,
        });

        expect(buildOrganizationDeleteMessage('Globex', report)).toBe(
            expectedMessage(
                'Globex',
                '20 sessions, 12 knowledge documents, 12 storage files, 6 agents, 4 flow, and more (58 items total)'
            )
        );
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
