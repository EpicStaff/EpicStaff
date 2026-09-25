import { OrganizationDeleteReport, UserDeleteReport } from '@shared/models';

const MAX_LISTED_RESOURCES = 5;

export function buildOrganizationDeleteMessage(name: string, report: OrganizationDeleteReport): string {
    const resources = Object.entries(report.affected_resources).sort(
        ([firstName, firstCount], [secondName, secondCount]) =>
            secondCount - firstCount || firstName.localeCompare(secondName)
    );

    let impact = 'no additional data';
    if (resources.length > 0) {
        const listedResources = resources
            .slice(0, MAX_LISTED_RESOURCES)
            .map(([resourceName, count]) => `${count} ${resourceName.replaceAll('_', ' ')}`);
        const moreResources = resources.length > MAX_LISTED_RESOURCES ? ', and more' : '';
        const totalCount = resources.reduce((sum, [, count]) => sum + count, 0);
        impact = `${listedResources.join(', ')}${moreResources} (${totalCount} items total)`;
    }

    return `<strong>${name}</strong> and everything it owns will be permanently deleted: ${impact}.`;
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
