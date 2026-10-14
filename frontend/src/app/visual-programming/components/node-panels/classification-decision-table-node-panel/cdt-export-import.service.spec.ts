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

describe('CdtExportImportService execution timeout', () => {
    const service = new CdtExportImportService();

    function exportData(executionTimeout: number | null) {
        return service.buildExportData({
            nodeName: 'Triage',
            preCode: '',
            preLibraries: [],
            preInputMap: {},
            preOutputVariablePath: null,
            preUseStorage: false,
            postCode: '',
            postLibraries: [],
            postInputMap: {},
            postOutputVariablePath: null,
            postUseStorage: false,
            defaultLlmConfig: null,
            executionTimeout,
            conditionGroups: [],
            prompts: {},
        });
    }

    function importedTimeout(fileContent: Record<string, unknown>): number | null {
        const result = service.parseJson(JSON.stringify({ condition_groups: [], ...fileContent }));
        if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);
        return result.data.execution_timeout;
    }

    it('keeps the timeout through a JSON export and import', () => {
        const result = service.parseJson(service.exportToJson(exportData(7)));

        expect('data' in result && result.data.execution_timeout).toBe(7);
    });

    it('writes the timeout into the CSV metadata, and leaves it empty for a node without one', () => {
        expect(service.exportToCsv(exportData(7)).split('\n')).toContain('execution_timeout,7');
        expect(service.exportToCsv(exportData(null)).split('\n')).toContain('execution_timeout,');
    });

    it('reads no timeout from a file exported before nodes had one', () => {
        expect(importedTimeout({})).toBeNull();
    });

    it.each([0, -2, 2.5, 'soon', true])('reads no timeout from a file holding %s, which no node may set', (value) => {
        expect(importedTimeout({ execution_timeout: value })).toBeNull();
    });

    it('carries the timeout of a node exported by the backend into the CSV of selected nodes', () => {
        const data = service.partialExportNodeToCdtExportData({
            ClassificationDecisionTableNode: [{ node_name: 'Triage', condition_groups: [], execution_timeout: 12 }],
        });

        expect(data.execution_timeout).toBe(12);
        expect(service.exportToCsv(data).split('\n')).toContain('execution_timeout,12');
    });
});
