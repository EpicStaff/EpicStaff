import { DeleteReport } from '@shared/models';

export function buildDeleteImpactMessage(name: string, report: DeleteReport): string {
    const topModels = report.database.by_model
        .slice(0, 5)
        .map((entry) => `${entry.count} ${entry.model.split('.').pop()}`);
    const moreModels = report.database.by_model.length > topModels.length ? ', and more' : '';

    const externalCount = report.external.reduce((sum, item) => sum + (item.objects ?? 0), 0);

    const impactParts: string[] = [];
    if (topModels.length > 0) {
        impactParts.push(`${topModels.join(', ')}${moreModels} (${report.database.total} records total)`);
    }
    if (externalCount > 0) {
        impactParts.push(`${externalCount} stored file${externalCount === 1 ? '' : 's'}`);
    }

    const impact = impactParts.length > 0 ? impactParts.join(' and ') : 'no additional data';

    return `<strong>${name}</strong> and everything it owns will be permanently deleted: ${impact}.`;
}
