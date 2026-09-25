import { ConfirmationBreakdownItem } from '@shared/components';
import { OrganizationDeleteReport, UserDeleteReport } from '@shared/models';
import { escapeHtml } from '@shared/utils';

import { HardDeleteContent } from '../models/hard-delete-content.model';
import { UserDeleteIdentity } from '../models/user-delete-identity.model';

export function buildOrganizationDeleteContent(name: string, report: OrganizationDeleteReport): HardDeleteContent {
    return {
        message: `You are about to permanently delete <strong>${escapeHtml(name)}</strong> organization. This action is irreversible.`,
        breakdown: {
            title: 'Resources to delete',
            items: buildDeleteBreakdownItems(report.affected_resources),
        },
    };
}

export function buildUserDeleteContent(user: UserDeleteIdentity, report: UserDeleteReport): HardDeleteContent {
    const message = `The user account for <strong>${escapeHtml(describeUser(user))}</strong> will be permanently deleted from the EpicStaff system.`;
    const caution = buildUserDeleteCaution(report);

    return caution ? { message, caution, cautionTitle: 'Caution' } : { message };
}

export function buildDeleteBreakdownItems(affectedResources: Record<string, number>): ConfirmationBreakdownItem[] {
    return Object.entries(affectedResources)
        .sort(
            ([firstName, firstCount], [secondName, secondCount]) =>
                secondCount - firstCount || firstName.localeCompare(secondName)
        )
        .map(([resourceName, count]) => ({ label: capitalize(resourceName.replaceAll('_', ' ')), count }));
}

function describeUser({ name, email }: UserDeleteIdentity): string {
    if (name && email) return `${name} (${email})`;
    return name || email || 'this user';
}

function buildUserDeleteCaution(report: UserDeleteReport): string | null {
    const membershipCount = report.affected_resources['memberships'] ?? 0;
    const apiKeyCount = report.affected_resources['api_keys'] ?? 0;

    const consequences: string[] = [];
    if (membershipCount > 0) {
        consequences.push(`they will lose access to ${pluralize(membershipCount, 'organization', 'organizations')}`);
    }
    if (apiKeyCount > 0) {
        consequences.push(`${pluralize(apiKeyCount, 'API key', 'API keys')} will stop working`);
    }

    return consequences.length > 0 ? `${capitalize(consequences.join(', and '))}.` : null;
}

function pluralize(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`;
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
