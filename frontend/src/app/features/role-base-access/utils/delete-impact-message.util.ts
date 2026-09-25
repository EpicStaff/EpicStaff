import { ConfirmationBreakdownItem } from '@shared/components';
import { UserDeleteReport } from '@shared/models';

export function buildOrganizationDeleteMessage(name: string): string {
    return `You are about to permanently delete <strong>${name}</strong> organization. This action is irreversible.`;
}

export function buildDeleteBreakdownItems(affectedResources: Record<string, number>): ConfirmationBreakdownItem[] {
    return Object.entries(affectedResources)
        .sort(
            ([firstName, firstCount], [secondName, secondCount]) =>
                secondCount - firstCount || firstName.localeCompare(secondName)
        )
        .map(([resourceName, count]) => ({ label: capitalize(resourceName.replaceAll('_', ' ')), count }));
}

export function buildUserDeleteMessage(name: string, report: UserDeleteReport): string {
    const membershipCount = report.affected_resources['memberships'] ?? 0;
    const apiKeyCount = report.affected_resources['api_keys'] ?? 0;

    const consequences: string[] = [];
    if (membershipCount > 0) {
        consequences.push(`they will lose access to ${pluralize(membershipCount, 'organization', 'organizations')}`);
    }
    if (apiKeyCount > 0) {
        consequences.push(`${pluralize(apiKeyCount, 'API key', 'API keys')} will stop working`);
    }

    const consequenceSentence = consequences.length > 0 ? ` ${capitalize(consequences.join(', and '))}.` : '';
    const keptContentSentence = membershipCount > 0 ? ' Content they created in organizations is kept.' : '';

    return `<strong>${name}</strong> will be permanently deleted.${consequenceSentence}${keptContentSentence}`;
}

function pluralize(count: number, singular: string, plural: string): string {
    return `${count} ${count === 1 ? singular : plural}`;
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1);
}
