import { OrganizationDeleteReport, UserDeleteReport } from '@shared/models';

import {
    buildDeleteBreakdownItems,
    buildOrganizationDeleteContent,
    buildUserDeleteContent,
} from './delete-impact-message.util';

function userReport(affectedResources: Record<string, number>): UserDeleteReport {
    return { user_id: 7, affected_resources: affectedResources };
}

function organizationReport(affectedResources: Record<string, number>): OrganizationDeleteReport {
    return { organization_id: 3, affected_resources: affectedResources };
}

describe('buildOrganizationDeleteContent', () => {
    it('warns that the organization will be permanently deleted and lists affected resources', () => {
        expect(buildOrganizationDeleteContent('Acme', organizationReport({ agents: 2, crews: 5 }))).toEqual({
            message:
                'You are about to permanently delete <strong>Acme</strong> organization. This action is irreversible.',
            breakdown: {
                title: 'Resources to delete',
                items: [
                    { label: 'Crews', count: 5 },
                    { label: 'Agents', count: 2 },
                ],
            },
        });
    });

    it('has no caution', () => {
        const content = buildOrganizationDeleteContent('Acme', organizationReport({ agents: 2 }));

        expect(content.caution).toBeUndefined();
        expect(content.cautionTitle).toBeUndefined();
    });

    it('escapes markup in the organization name', () => {
        expect(buildOrganizationDeleteContent('<img src=x>', organizationReport({})).message).toBe(
            'You are about to permanently delete <strong>&lt;img src=x&gt;</strong> organization. This action is irreversible.'
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

describe('buildUserDeleteContent', () => {
    const JANE = { name: 'Jane', email: 'jane@example.com' };
    const JANE_MESSAGE =
        'The user account for <strong>Jane (jane@example.com)</strong> will be permanently deleted from the EpicStaff system.';

    it('names the user with name and email', () => {
        expect(buildUserDeleteContent(JANE, userReport({})).message).toBe(JANE_MESSAGE);
    });

    it('escapes markup in the name and email so they cannot hide the real identity', () => {
        expect(buildUserDeleteContent({ name: 'Alice<!--', email: 'a&b@example.com' }, userReport({})).message).toBe(
            'The user account for <strong>Alice&lt;!-- (a&amp;b@example.com)</strong> will be permanently deleted from the EpicStaff system.'
        );
    });

    it('names the user by email only when the name is null', () => {
        expect(buildUserDeleteContent({ name: null, email: 'jane@example.com' }, userReport({})).message).toBe(
            'The user account for <strong>jane@example.com</strong> will be permanently deleted from the EpicStaff system.'
        );
    });

    it('names the user by email only when the name is missing', () => {
        expect(buildUserDeleteContent({ email: 'jane@example.com' }, userReport({})).message).toBe(
            'The user account for <strong>jane@example.com</strong> will be permanently deleted from the EpicStaff system.'
        );
    });

    it('names the user by name only when the email is empty', () => {
        expect(buildUserDeleteContent({ name: 'Jane', email: '' }, userReport({})).message).toBe(
            'The user account for <strong>Jane</strong> will be permanently deleted from the EpicStaff system.'
        );
    });

    it('falls back to a generic label when both name and email are missing', () => {
        expect(buildUserDeleteContent({ name: '', email: '' }, userReport({})).message).toBe(
            'The user account for <strong>this user</strong> will be permanently deleted from the EpicStaff system.'
        );
    });

    it('never includes a breakdown', () => {
        expect(buildUserDeleteContent(JANE, userReport({ memberships: 2, api_keys: 1 })).breakdown).toBeUndefined();
    });

    it('cautions about lost organizations and broken API keys when both apply', () => {
        expect(buildUserDeleteContent(JANE, userReport({ memberships: 2, api_keys: 3 }))).toEqual({
            message: JANE_MESSAGE,
            cautionTitle: 'Caution',
            caution: 'They will lose access to 2 organizations, and 3 API keys will stop working.',
        });
    });

    it('mentions only lost organizations when the user has no API keys', () => {
        expect(buildUserDeleteContent(JANE, userReport({ memberships: 3 })).caution).toBe(
            'They will lose access to 3 organizations.'
        );
    });

    it('mentions only broken API keys, capitalized, when the user has no memberships', () => {
        expect(buildUserDeleteContent(JANE, userReport({ api_keys: 3 })).caution).toBe('3 API keys will stop working.');
    });

    it('uses the singular form for a count of one', () => {
        expect(buildUserDeleteContent(JANE, userReport({ memberships: 1, api_keys: 1 })).caution).toBe(
            'They will lose access to 1 organization, and 1 API key will stop working.'
        );
    });

    it('omits the caution when nothing is affected', () => {
        expect(buildUserDeleteContent(JANE, userReport({}))).toEqual({ message: JANE_MESSAGE });
    });

    it('omits the caution when only resources other than memberships and API keys are affected', () => {
        const report = userReport({ tool_favorites: 5, avatar: 1, memberships: 0, api_keys: 0 });

        expect(buildUserDeleteContent(JANE, report)).toEqual({ message: JANE_MESSAGE });
    });
});
