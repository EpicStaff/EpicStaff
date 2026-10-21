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

describe('CdtExportImportService execution timeouts', () => {
    const service = new CdtExportImportService();

    function exportData(preExecutionTimeout: number | undefined, postExecutionTimeout: number | undefined) {
        return service.buildExportData({
            nodeName: 'Triage',
            preCode: 'def main(): pass',
            preLibraries: [],
            preExecutionTimeout,
            preInputMap: {},
            preOutputVariablePath: null,
            preUseStorage: false,
            postCode: 'def main(): pass',
            postLibraries: [],
            postExecutionTimeout,
            postInputMap: {},
            postOutputVariablePath: null,
            postUseStorage: false,
            defaultLlmConfig: null,
            conditionGroups: [],
            prompts: {},
        });
    }

    function csvRows(data: ReturnType<typeof exportData>): string[] {
        return service.exportToCsv(data).split('\n');
    }

    it('keeps the pre- and post-computation timeouts through a JSON export and import', () => {
        const result = service.parseJson(service.exportToJson(exportData(90, 45)));
        if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);

        expect(result.data.pre_python_code.execution_timeout).toBe(90);
        expect(result.data.post_python_code.execution_timeout).toBe(45);
    });

    it('imports no timeout for a code without one', () => {
        const result = service.parseJson(service.exportToJson(exportData(undefined, 45)));
        if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);

        expect(result.data.pre_python_code.execution_timeout).toBeNull();
        expect(result.data.post_python_code.execution_timeout).toBe(45);
    });

    it.each([0, -30, 7.5, '90', 'soon'])(
        'imports %s as no timeout: only a positive whole number of seconds is one',
        (value) => {
            const json = JSON.parse(service.exportToJson(exportData(90, 45))) as Record<
                string,
                Record<string, unknown>
            >;
            json['pre_python_code']['execution_timeout'] = value;
            const result = service.parseJson(JSON.stringify(json));
            if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);

            expect(result.data.pre_python_code.execution_timeout).toBe(value === '90' ? 90 : null);
        }
    );

    it('writes each timeout into the CSV metadata, and leaves it empty for a code without one', () => {
        expect(csvRows(exportData(90, 45))).toEqual(
            expect.arrayContaining(['pre_python_code_execution_timeout,90', 'post_python_code_execution_timeout,45'])
        );
        expect(csvRows(exportData(undefined, undefined))).toEqual(
            expect.arrayContaining(['pre_python_code_execution_timeout,', 'post_python_code_execution_timeout,'])
        );
    });

    it('carries the timeouts of a node exported by the backend into the CSV of selected nodes', () => {
        const data = service.partialExportNodeToCdtExportData({
            ClassificationDecisionTableNode: [
                {
                    node_name: 'Triage',
                    condition_groups: [],
                    pre_python_code: { code: 'def main(): pass', libraries: '', execution_timeout: 90 },
                    post_python_code: { code: 'def main(): pass', libraries: '' },
                },
            ],
        });

        expect(data.pre_python_code.execution_timeout).toBe(90);
        expect(data.post_python_code.execution_timeout).toBeNull();
        expect(csvRows(data)).toEqual(
            expect.arrayContaining(['pre_python_code_execution_timeout,90', 'post_python_code_execution_timeout,'])
        );
    });
});
