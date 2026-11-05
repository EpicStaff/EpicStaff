import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { SystemOneConfig } from '@shared/models';
import { SystemOneConfigStorageService } from '@shared/services';

import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { CdtExportImportService } from './cdt-export-import.service';

const KNOWN_CONFIG = { id: 7, custom_name: 'jev' } as SystemOneConfig;

function createService(options: { configs?: SystemOneConfig[]; loaded?: boolean } = {}): CdtExportImportService {
    const configs = signal(options.configs ?? [KNOWN_CONFIG]);
    const loaded = signal(options.loaded ?? true);
    TestBed.configureTestingModule({
        providers: [
            {
                provide: SystemOneConfigStorageService,
                useValue: { configs, isConfigsLoaded: loaded },
            },
        ],
    });
    return TestBed.inject(CdtExportImportService);
}

describe('CdtExportImportService route code import', () => {
    let service: CdtExportImportService;

    beforeEach(() => {
        service = createService();
    });

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
    let service: CdtExportImportService;

    beforeEach(() => {
        service = createService();
    });

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

describe('CdtExportImportService System One entries', () => {
    const SYSTEM_ONE_PROMPT: PromptConfig = {
        prompt_text: '',
        llm_config: null,
        output_schema: null,
        result_variable: 'company_check',
        variable_mappings: {},
        kind: 'system_one',
        system_one_config: 7,
        questions: { is_engineering: { type: 'noul', instructions: 'Engineering?' } },
        input_map: { company: 'variables.company' },
    };

    function exportOf(service: CdtExportImportService, prompts: Record<string, PromptConfig>) {
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
            conditionGroups: [],
            prompts,
        });
    }

    function importOf(service: CdtExportImportService, json: string) {
        const result = service.parseJson(json);
        if (!('data' in result)) throw new Error(`Import failed: ${result.errors.join('; ')}`);
        return service.toPromptRecord(result.data);
    }

    it("keeps the entry's kind, config, questions and input map through a JSON export and import", () => {
        const service = createService();

        const imported = importOf(
            service,
            service.exportToJson(exportOf(service, { company_check: SYSTEM_ONE_PROMPT }))
        );

        expect(imported['company_check']).toMatchObject({
            kind: 'system_one',
            system_one_config: 7,
            questions: SYSTEM_ONE_PROMPT.questions,
            input_map: SYSTEM_ONE_PROMPT.input_map,
        });
    });

    it('imports a config that does not exist in this workspace as no config, and keeps the rest', () => {
        const service = createService({ configs: [{ ...KNOWN_CONFIG, id: 99 }] });

        const imported = importOf(
            service,
            service.exportToJson(exportOf(service, { company_check: SYSTEM_ONE_PROMPT }))
        );

        expect(imported['company_check']).toMatchObject({
            kind: 'system_one',
            system_one_config: null,
            questions: SYSTEM_ONE_PROMPT.questions,
            input_map: SYSTEM_ONE_PROMPT.input_map,
        });
    });

    it('keeps the config id while the workspace configs have not loaded yet', () => {
        const service = createService({ configs: [], loaded: false });

        const imported = importOf(
            service,
            service.exportToJson(exportOf(service, { company_check: SYSTEM_ONE_PROMPT }))
        );

        expect(imported['company_check'].system_one_config).toBe(7);
    });

    it('drops imported questions the backend would refuse, and keeps the valid ones', () => {
        const service = createService();
        const json = JSON.stringify({
            condition_groups: [],
            prompt_configs: [
                {
                    prompt_key: 'p',
                    kind: 'system_one',
                    questions: {
                        is_engineering: { type: 'noul', instructions: 'Engineering?' },
                        class: { type: 'noul', instructions: 'Reserved word as a name' },
                        no_instructions: { type: 'noul', instructions: '' },
                        no_options: { type: 'choice', instructions: 'Which?', criteria: {} },
                        no_levels: { type: 'score', instructions: 'How senior?', criteria: [] },
                    },
                },
            ],
        });

        expect(importOf(service, json)['p'].questions).toEqual({
            is_engineering: { type: 'noul', instructions: 'Engineering?' },
        });
    });

    it.each([undefined, 'llm', 'nonsense', 3])('imports kind %s as an LLM entry', (kind) => {
        const service = createService();
        const json = JSON.stringify({
            condition_groups: [],
            prompt_configs: [{ prompt_key: 'p', prompt_text: 'Hi', llm_config: 2, kind }],
        });

        expect(importOf(service, json)['p']).toMatchObject({ kind: 'llm', llm_config: 2, system_one_config: null });
    });

    it('writes kind, config, questions and input map as CSV prompt columns', () => {
        const service = createService();
        const lines = service.exportToCsv(exportOf(service, { company_check: SYSTEM_ONE_PROMPT })).split('\n');
        const header = lines[lines.indexOf('#prompt_configs') + 1].split(',');
        const row = lines[lines.indexOf('#prompt_configs') + 2];

        expect(header).toEqual(expect.arrayContaining(['kind', 'system_one_config', 'questions', 'input_map']));
        expect(row).toContain('system_one,7,');
        expect(row).toContain('Engineering?');
        expect(row).toContain('variables.company');
    });
});
