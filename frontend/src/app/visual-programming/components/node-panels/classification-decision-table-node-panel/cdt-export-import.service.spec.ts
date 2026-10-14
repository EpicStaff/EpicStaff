import { CdtExportImportService } from './cdt-export-import.service';

describe('CdtExportImportService route code import', () => {
    const service = new CdtExportImportService();

    function importedRouteCodes(routeCodes: unknown[]): (string | null)[] {
        const content = JSON.stringify({
            condition_groups: routeCodes.map((route_code, index) => ({
                group_name: `Condition ${index + 1}`,
                route_code,
            })),
        });
        const result = service.parseJson(content);
        if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);
        return result.data.condition_groups.map((group) => group.route_code);
    }

    function partialExportRouteCodes(routeCodes: unknown[]): (string | null)[] {
        const data = service.partialExportNodeToCdtExportData({
            ClassificationDecisionTableNode: [
                {
                    condition_groups: routeCodes.map((route_code, index) => ({
                        group_name: `Condition ${index + 1}`,
                        route_code,
                    })),
                },
            ],
        });
        return data.condition_groups.map((group) => group.route_code);
    }

    describe('parseJson', () => {
        it('trims surrounding whitespace and keeps inner spaces', () => {
            expect(importedRouteCodes(['  approve ', ' needs review\t'])).toEqual(['approve', 'needs review']);
        });

        it('imports whitespace-only, empty and missing codes as null', () => {
            expect(importedRouteCodes(['   ', '', null, 42])).toEqual([null, null, null, null]);
        });
    });

    describe('partialExportNodeToCdtExportData', () => {
        it('trims surrounding whitespace', () => {
            expect(partialExportRouteCodes([' approve  '])).toEqual(['approve']);
        });

        it('imports whitespace-only and missing codes as null', () => {
            expect(partialExportRouteCodes(['  ', undefined])).toEqual([null, null]);
        });
    });
});
