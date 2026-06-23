import { Injectable } from '@angular/core';

import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';

export interface CdtExportPythonCode {
    code: string;
    libraries: string[];
}

export interface CdtExportConditionGroup {
    group_name: string;
    order: number;
    expression: string | null;
    prompt_id: string | null;
    manipulation: string | null;
    continue_flag: boolean;
    route_code: string | null;
    dock_visible: boolean;
    field_expressions: Record<string, string>;
    field_manipulations: Record<string, string>;
    section: string | null;
}

export interface CdtExportPromptConfig {
    prompt_key: string;
    prompt_text: string;
    llm_config: number | null;
    output_schema: Record<string, unknown> | string | null;
    result_variable: string;
    variable_mappings: Record<string, string>;
}

export interface CdtExportData {
    node_name: string;
    pre_python_code: CdtExportPythonCode;
    pre_input_map: Record<string, string>;
    pre_output_variable_path: string | null;
    post_python_code: CdtExportPythonCode;
    post_input_map: Record<string, string>;
    post_output_variable_path: string | null;
    default_llm_config: number | null;
    condition_groups: CdtExportConditionGroup[];
    prompt_configs: CdtExportPromptConfig[];
}

export type CdtParseResult = { data: CdtExportData } | { errors: string[] };

const CONDITION_GROUP_COLUMNS = [
    'group_name',
    'order',
    'expression',
    'prompt_id',
    'manipulation',
    'continue_flag',
    'route_code',
    'dock_visible',
    'field_expressions',
    'field_manipulations',
    'section',
] as const;

const PROMPT_CONFIG_COLUMNS = [
    'prompt_key',
    'prompt_text',
    'llm_config',
    'output_schema',
    'result_variable',
    'variable_mappings',
] as const;

@Injectable({ providedIn: 'root' })
export class CdtExportImportService {
    public exportToJson(data: CdtExportData): string {
        return JSON.stringify(data, null, 2);
    }

    public exportToCsv(data: CdtExportData): string {
        const metadata = [
            '#metadata',
            this.csvRow(['node_name', data.node_name ?? '']),
            this.csvRow(['pre_input_map', JSON.stringify(data.pre_input_map ?? {})]),
            this.csvRow(['pre_output_variable_path', data.pre_output_variable_path ?? '']),
            this.csvRow(['pre_python_code_code', data.pre_python_code?.code ?? '']),
            this.csvRow(['pre_python_code_libraries', JSON.stringify(data.pre_python_code?.libraries ?? [])]),
            this.csvRow(['post_input_map', JSON.stringify(data.post_input_map ?? {})]),
            this.csvRow(['post_output_variable_path', data.post_output_variable_path ?? '']),
            this.csvRow(['post_python_code_code', data.post_python_code?.code ?? '']),
            this.csvRow(['post_python_code_libraries', JSON.stringify(data.post_python_code?.libraries ?? [])]),
            this.csvRow(['default_llm_config', data.default_llm_config == null ? '' : String(data.default_llm_config)]),
        ].join('\n');

        const conditionGroups = [
            '#condition_groups',
            this.csvRow([...CONDITION_GROUP_COLUMNS]),
            ...data.condition_groups.map((group) =>
                this.csvRow([
                    group.group_name ?? '',
                    String(group.order ?? 0),
                    group.expression ?? '',
                    group.prompt_id ?? '',
                    group.manipulation ?? '',
                    String(group.continue_flag ?? false),
                    group.route_code ?? '',
                    String(group.dock_visible ?? true),
                    JSON.stringify(group.field_expressions ?? {}),
                    JSON.stringify(group.field_manipulations ?? {}),
                    group.section ?? '',
                ])
            ),
        ].join('\n');

        const promptConfigs = [
            '#prompt_configs',
            this.csvRow([...PROMPT_CONFIG_COLUMNS]),
            ...data.prompt_configs.map((prompt) =>
                this.csvRow([
                    prompt.prompt_key ?? '',
                    prompt.prompt_text ?? '',
                    prompt.llm_config == null ? '' : String(prompt.llm_config),
                    prompt.output_schema == null ? '' : JSON.stringify(prompt.output_schema),
                    prompt.result_variable ?? '',
                    JSON.stringify(prompt.variable_mappings ?? {}),
                ])
            ),
        ].join('\n');

        return [metadata, conditionGroups, promptConfigs].join('\n\n');
    }

    public downloadFile(content: string, filename: string, mimeType: string): void {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    }

    public parseJson(content: string): CdtParseResult {
        let raw: unknown;
        try {
            raw = JSON.parse(content);
        } catch {
            return { errors: ['File is not valid JSON.'] };
        }
        if (!raw || typeof raw !== 'object') {
            return { errors: ['JSON root must be an object.'] };
        }

        const obj = raw as Record<string, unknown>;
        const errors: string[] = [];

        const rawGroups = obj['condition_groups'];
        if (!Array.isArray(rawGroups)) {
            errors.push('"condition_groups" must be an array.');
        }

        const conditionGroups: CdtExportConditionGroup[] = [];
        if (Array.isArray(rawGroups)) {
            rawGroups.forEach((g, index) => {
                const group = (g ?? {}) as Record<string, unknown>;
                const name = group['group_name'];
                if (typeof name !== 'string' || name.trim().length === 0) {
                    errors.push(
                        `Condition group #${index + 1}: "group_name" is required and must be a non-empty string.`
                    );
                }
                const order = group['order'];
                if (order != null && typeof order !== 'number') {
                    errors.push(`Condition group #${index + 1}: "order" must be a number.`);
                }
                conditionGroups.push(this.normalizeConditionGroup(group, index));
            });
        }

        const rawPrompts = obj['prompt_configs'];
        const promptConfigs: CdtExportPromptConfig[] = [];
        if (Array.isArray(rawPrompts)) {
            rawPrompts.forEach((p) =>
                promptConfigs.push(this.normalizePromptConfig((p ?? {}) as Record<string, unknown>))
            );
        }

        if (errors.length > 0) {
            return { errors };
        }

        const preCode = (obj['pre_python_code'] ?? {}) as Record<string, unknown>;
        const postCode = (obj['post_python_code'] ?? {}) as Record<string, unknown>;

        return {
            data: {
                node_name: this.asString(obj['node_name']),
                pre_python_code: {
                    code: this.asString(preCode['code']),
                    libraries: this.asStringArray(preCode['libraries']),
                },
                pre_input_map: this.asStringRecord(obj['pre_input_map']),
                pre_output_variable_path: this.asNullableString(obj['pre_output_variable_path']),
                post_python_code: {
                    code: this.asString(postCode['code']),
                    libraries: this.asStringArray(postCode['libraries']),
                },
                post_input_map: this.asStringRecord(obj['post_input_map']),
                post_output_variable_path: this.asNullableString(obj['post_output_variable_path']),
                default_llm_config: this.asNullableNumber(obj['default_llm_config']),
                condition_groups: conditionGroups,
                prompt_configs: promptConfigs,
            },
        };
    }

    public parseCsv(content: string): CdtParseResult {
        const sections = this.splitCsvSections(content);
        const errors: string[] = [];

        if (!sections['metadata']) errors.push('CSV is missing the #metadata section.');
        if (!sections['condition_groups']) errors.push('CSV is missing the #condition_groups section.');
        if (!sections['prompt_configs']) errors.push('CSV is missing the #prompt_configs section.');
        if (errors.length > 0) {
            return { errors };
        }

        const metadata = this.parseMetadataSection(sections['metadata']);

        const groupRows = this.parseTabularSection(sections['condition_groups']);
        const conditionGroups: CdtExportConditionGroup[] = [];
        groupRows.forEach((row, index) => {
            const name = (row['group_name'] ?? '').trim();
            if (name.length === 0) {
                errors.push(`Condition group #${index + 1}: "group_name" is required.`);
            }
            const orderRaw = (row['order'] ?? '').trim();
            const order = Number(orderRaw);
            if (orderRaw.length === 0 || Number.isNaN(order)) {
                errors.push(`Condition group #${index + 1}: "order" must be a number.`);
            }
            conditionGroups.push({
                group_name: name,
                order: Number.isNaN(order) ? index + 1 : order,
                expression: this.emptyToNull(row['expression']),
                prompt_id: this.emptyToNull(row['prompt_id']),
                manipulation: this.emptyToNull(row['manipulation']),
                continue_flag: (row['continue_flag'] ?? '').trim().toLowerCase() === 'true',
                route_code: this.emptyToNull(row['route_code']),
                dock_visible: (row['dock_visible'] ?? 'true').trim().toLowerCase() !== 'false',
                field_expressions: this.parseJsonCell(row['field_expressions']),
                field_manipulations: this.parseJsonCell(row['field_manipulations']),
                section: this.emptyToNull(row['section']),
            });
        });

        const promptRows = this.parseTabularSection(sections['prompt_configs']);
        const promptConfigs: CdtExportPromptConfig[] = promptRows.map((row) => ({
            prompt_key: (row['prompt_key'] ?? '').trim(),
            prompt_text: row['prompt_text'] ?? '',
            llm_config: this.asNullableNumber(this.emptyToNull(row['llm_config'])),
            output_schema: this.parseSchemaCell(row['output_schema']),
            result_variable: row['result_variable'] ?? '',
            variable_mappings: this.parseJsonCell(row['variable_mappings']),
        }));

        if (errors.length > 0) {
            return { errors };
        }

        return {
            data: {
                node_name: metadata['node_name'] ?? '',
                pre_python_code: {
                    code: metadata['pre_python_code_code'] ?? '',
                    libraries: this.asStringArray(this.tryParseJson(metadata['pre_python_code_libraries'])),
                },
                pre_input_map: this.asStringRecord(this.tryParseJson(metadata['pre_input_map'])),
                pre_output_variable_path: this.emptyToNull(metadata['pre_output_variable_path']),
                post_python_code: {
                    code: metadata['post_python_code_code'] ?? '',
                    libraries: this.asStringArray(this.tryParseJson(metadata['post_python_code_libraries'])),
                },
                post_input_map: this.asStringRecord(this.tryParseJson(metadata['post_input_map'])),
                post_output_variable_path: this.emptyToNull(metadata['post_output_variable_path']),
                default_llm_config: this.asNullableNumber(this.emptyToNull(metadata['default_llm_config'])),
                condition_groups: conditionGroups,
                prompt_configs: promptConfigs,
            },
        };
    }

    public cdtExportDataToPartialImportJson(data: CdtExportData): string {
        const promptIdToFakeId = new Map<string, number>();
        const promptConfigs = data.prompt_configs.map((prompt, index) => {
            const fakeId = index + 1;
            if (prompt.prompt_key) {
                promptIdToFakeId.set(prompt.prompt_key, fakeId);
            }
            const result: Record<string, unknown> = {
                id: fakeId,
                prompt_key: prompt.prompt_key ?? '',
                prompt_text: prompt.prompt_text ?? '',
                llm_config: prompt.llm_config ?? null,
                output_schema: prompt.output_schema ?? {},
                result_variable: prompt.result_variable ?? 'prompt_result',
                variable_mappings: prompt.variable_mappings ?? {},
            };
            return result;
        });

        const conditionGroups = data.condition_groups.map((group) => {
            const promptFakeId = group.prompt_id != null ? (promptIdToFakeId.get(group.prompt_id) ?? null) : null;
            const result: Record<string, unknown> = {
                id: 0,
                group_name: group.group_name ?? '',
                order: group.order ?? 1,
                expression: group.expression ?? null,
                prompt: promptFakeId,
                manipulation: group.manipulation ?? null,
                continue_flag: group.continue_flag ?? false,
                next_node_id: null,
                dock_visible: group.dock_visible ?? true,
                field_expressions: group.field_expressions ?? {},
                field_manipulations: group.field_manipulations ?? {},
                route_code: group.route_code ?? null,
                section: group.section ?? null,
                metadata: {},
            };
            return result;
        });

        const node: Record<string, unknown> = {
            id: 0,
            node_name: data.node_name ?? '',
            pre_input_map: data.pre_input_map ?? {},
            pre_output_variable_path: data.pre_output_variable_path ?? null,
            post_input_map: data.post_input_map ?? {},
            post_output_variable_path: data.post_output_variable_path ?? null,
            default_llm_config: data.default_llm_config ?? null,
            default_next_node_id: null,
            next_error_node_id: null,
            metadata: {},
            condition_groups: conditionGroups,
            prompt_configs: promptConfigs,
        };

        return JSON.stringify({ ClassificationDecisionTableNode: [node] }, null, 2);
    }

    public partialExportNodeToCdtExportData(nodeJson: Record<string, unknown>): CdtExportData {
        const nodes = nodeJson['ClassificationDecisionTableNode'];
        if (!Array.isArray(nodes) || nodes.length === 0) {
            return {
                node_name: '',
                pre_python_code: { code: '', libraries: [] },
                pre_input_map: {},
                pre_output_variable_path: null,
                post_python_code: { code: '', libraries: [] },
                post_input_map: {},
                post_output_variable_path: null,
                default_llm_config: null,
                condition_groups: [],
                prompt_configs: [],
            };
        }

        const node = (nodes[0] ?? {}) as Record<string, unknown>;

        const rawPreCode = (node['pre_python_code'] ?? {}) as Record<string, unknown>;
        const rawPostCode = (node['post_python_code'] ?? {}) as Record<string, unknown>;

        const rawPromptConfigs = Array.isArray(node['prompt_configs'])
            ? (node['prompt_configs'] as Record<string, unknown>[])
            : [];

        const promptConfigs: CdtExportPromptConfig[] = rawPromptConfigs.map((p) => this.normalizePromptConfig(p));

        // Build a lookup from numeric prompt id → prompt_key
        const promptIdToKey = new Map<number, string>();
        rawPromptConfigs.forEach((p) => {
            const id = p['id'];
            const key = p['prompt_key'];
            if (typeof id === 'number' && typeof key === 'string') {
                promptIdToKey.set(id, key);
            }
        });

        const rawConditionGroups = Array.isArray(node['condition_groups'])
            ? (node['condition_groups'] as Record<string, unknown>[])
            : [];

        const conditionGroups: CdtExportConditionGroup[] = rawConditionGroups.map((g, index) => {
            const promptIntId = typeof g['prompt'] === 'number' ? (g['prompt'] as number) : null;
            const promptId = promptIntId != null ? (promptIdToKey.get(promptIntId) ?? null) : null;
            return {
                group_name: this.asString(g['group_name']),
                order: typeof g['order'] === 'number' ? (g['order'] as number) : index + 1,
                expression: this.asNullableString(g['expression']),
                prompt_id: promptId,
                manipulation: this.asNullableString(g['manipulation']),
                continue_flag: g['continue_flag'] === true,
                route_code: this.asNullableString(g['route_code']),
                dock_visible: g['dock_visible'] !== false,
                field_expressions: this.asStringRecord(g['field_expressions']),
                field_manipulations: this.asStringRecord(g['field_manipulations']),
                section: this.asNullableString(g['section']),
            };
        });

        return {
            node_name: this.asString(node['node_name']),
            pre_python_code: {
                code: this.asString(rawPreCode['code']),
                libraries: this.asString(rawPreCode['libraries'])
                    .split('\n')
                    .filter((lib) => lib.trim().length > 0),
            },
            pre_input_map: this.asStringRecord(node['pre_input_map']),
            pre_output_variable_path: this.asNullableString(node['pre_output_variable_path']),
            post_python_code: {
                code: this.asString(rawPostCode['code']),
                libraries: this.asString(rawPostCode['libraries'])
                    .split('\n')
                    .filter((lib) => lib.trim().length > 0),
            },
            post_input_map: this.asStringRecord(node['post_input_map']),
            post_output_variable_path: this.asNullableString(node['post_output_variable_path']),
            default_llm_config: this.asNullableNumber(node['default_llm_config']),
            condition_groups: conditionGroups,
            prompt_configs: promptConfigs,
        };
    }

    public buildExportData(input: {
        nodeName: string;
        preCode: string;
        preLibraries: string[];
        preInputMap: Record<string, string>;
        preOutputVariablePath: string | null;
        postCode: string;
        postLibraries: string[];
        postInputMap: Record<string, string>;
        postOutputVariablePath: string | null;
        defaultLlmConfig: number | null;
        conditionGroups: ConditionGroup[];
        prompts: Record<string, PromptConfig>;
    }): CdtExportData {
        return {
            node_name: input.nodeName ?? '',
            pre_python_code: { code: input.preCode ?? '', libraries: input.preLibraries ?? [] },
            pre_input_map: input.preInputMap ?? {},
            pre_output_variable_path: input.preOutputVariablePath ?? null,
            post_python_code: { code: input.postCode ?? '', libraries: input.postLibraries ?? [] },
            post_input_map: input.postInputMap ?? {},
            post_output_variable_path: input.postOutputVariablePath ?? null,
            default_llm_config: input.defaultLlmConfig ?? null,
            condition_groups: (input.conditionGroups ?? []).map((group, index) => ({
                group_name: group.group_name ?? '',
                order: group.order ?? index + 1,
                expression: group.expression ?? null,
                prompt_id: group.prompt_id ?? null,
                manipulation: group.manipulation ?? null,
                continue_flag: group.continue_flag ?? group.continue ?? false,
                route_code: group.route_code ?? null,
                dock_visible: group.dock_visible ?? true,
                field_expressions: group.field_expressions ?? {},
                field_manipulations: group.field_manipulations ?? {},
                section: group.section ?? null,
            })),
            prompt_configs: Object.entries(input.prompts ?? {}).map(([key, config]) => ({
                prompt_key: key,
                prompt_text: config.prompt_text ?? '',
                llm_config: config.llm_config ?? null,
                output_schema: config.output_schema ?? null,
                result_variable: config.result_variable ?? '',
                variable_mappings: config.variable_mappings ?? {},
            })),
        };
    }

    public toConditionGroups(data: CdtExportData): ConditionGroup[] {
        return data.condition_groups.map((group) => ({
            group_name: group.group_name,
            group_type: 'simple',
            prompt_id: group.prompt_id,
            expression: group.expression,
            conditions: [],
            manipulation: group.manipulation,
            next_node: null,
            order: group.order,
            continue_flag: group.continue_flag,
            route_code: group.route_code ?? undefined,
            dock_visible: group.dock_visible,
            field_expressions: group.field_expressions,
            field_manipulations: group.field_manipulations,
            section: group.section,
        }));
    }

    public toPromptRecord(data: CdtExportData): Record<string, PromptConfig> {
        const record: Record<string, PromptConfig> = {};
        data.prompt_configs.forEach((prompt) => {
            if (!prompt.prompt_key) return;
            record[prompt.prompt_key] = {
                prompt_text: prompt.prompt_text,
                llm_config: prompt.llm_config,
                output_schema: prompt.output_schema,
                result_variable: prompt.result_variable,
                variable_mappings: prompt.variable_mappings,
            };
        });
        return record;
    }

    private csvRow(cells: string[]): string {
        return cells.map((cell) => this.csvEscape(cell)).join(',');
    }

    private csvEscape(value: string): string {
        const needsQuoting = /[",\n\r]/.test(value);
        if (!needsQuoting) return value;
        return '"' + value.replace(/"/g, '""') + '"';
    }

    private parseCsvLine(line: string): string[] {
        const cells: string[] = [];
        let current = '';
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            if (inQuotes) {
                if (char === '"') {
                    if (line[i + 1] === '"') {
                        current += '"';
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    current += char;
                }
            } else if (char === '"') {
                inQuotes = true;
            } else if (char === ',') {
                cells.push(current);
                current = '';
            } else {
                current += char;
            }
        }
        cells.push(current);
        return cells;
    }

    private splitCsvSections(content: string): Record<string, string[]> {
        const records = this.splitCsvRecords(content.replace(/\r\n/g, '\n'));
        const sections: Record<string, string[]> = {};
        let currentKey: string | null = null;
        for (const record of records) {
            const trimmed = record.trim();
            // Section markers are unquoted single-cell records like "#metadata".
            if (trimmed.startsWith('#') && !record.includes('"')) {
                currentKey = trimmed.slice(1).trim();
                sections[currentKey] = [];
                continue;
            }
            if (currentKey == null) continue;
            if (trimmed.length === 0) continue;
            sections[currentKey].push(record);
        }
        return sections;
    }

    /**
     * Splits raw CSV text into logical records. A newline only ends a record when
     * it is not inside a quoted field, so multiline values (e.g. Python code) survive.
     */
    private splitCsvRecords(content: string): string[] {
        const records: string[] = [];
        let current = '';
        let inQuotes = false;
        for (let i = 0; i < content.length; i++) {
            const char = content[i];
            if (char === '"') {
                inQuotes = !inQuotes;
                current += char;
            } else if (char === '\n' && !inQuotes) {
                records.push(current);
                current = '';
            } else {
                current += char;
            }
        }
        if (current.length > 0) {
            records.push(current);
        }
        return records;
    }

    private parseMetadataSection(lines: string[]): Record<string, string> {
        const result: Record<string, string> = {};
        for (const line of lines) {
            const cells = this.parseCsvLine(line);
            if (cells.length === 0) continue;
            const key = cells[0];
            result[key] = cells.slice(1).join(',');
        }
        return result;
    }

    private parseTabularSection(lines: string[]): Record<string, string>[] {
        if (lines.length === 0) return [];
        const header = this.parseCsvLine(lines[0]);
        const rows: Record<string, string>[] = [];
        for (let i = 1; i < lines.length; i++) {
            const cells = this.parseCsvLine(lines[i]);
            const row: Record<string, string> = {};
            header.forEach((col, idx) => {
                row[col] = cells[idx] ?? '';
            });
            rows.push(row);
        }
        return rows;
    }

    private normalizeConditionGroup(group: Record<string, unknown>, index: number): CdtExportConditionGroup {
        return {
            group_name: this.asString(group['group_name']),
            order: typeof group['order'] === 'number' ? (group['order'] as number) : index + 1,
            expression: this.asNullableString(group['expression']),
            prompt_id: this.asNullableString(group['prompt_id']),
            manipulation: this.asNullableString(group['manipulation']),
            continue_flag: group['continue_flag'] === true,
            route_code: this.asNullableString(group['route_code']),
            dock_visible: group['dock_visible'] !== false,
            field_expressions: this.asStringRecord(group['field_expressions']),
            field_manipulations: this.asStringRecord(group['field_manipulations']),
            section: this.asNullableString(group['section']),
        };
    }

    private normalizePromptConfig(prompt: Record<string, unknown>): CdtExportPromptConfig {
        const schema = prompt['output_schema'];
        return {
            prompt_key: this.asString(prompt['prompt_key']),
            prompt_text: this.asString(prompt['prompt_text']),
            llm_config: this.asNullableNumber(prompt['llm_config']),
            output_schema:
                schema == null ? null : typeof schema === 'string' ? schema : (schema as Record<string, unknown>),
            result_variable: this.asString(prompt['result_variable']),
            variable_mappings: this.asStringRecord(prompt['variable_mappings']),
        };
    }

    private parseJsonCell(value: string | undefined): Record<string, string> {
        return this.asStringRecord(this.tryParseJson(value));
    }

    private parseSchemaCell(value: string | undefined): Record<string, unknown> | string | null {
        if (value == null || value.trim().length === 0) return null;
        const parsed = this.tryParseJson(value);
        if (parsed && typeof parsed === 'object') return parsed as Record<string, unknown>;
        return value;
    }

    private tryParseJson(value: string | undefined): unknown {
        if (value == null || value.trim().length === 0) return undefined;
        try {
            return JSON.parse(value);
        } catch {
            return undefined;
        }
    }

    private asString(value: unknown): string {
        return typeof value === 'string' ? value : '';
    }

    private asNullableString(value: unknown): string | null {
        if (typeof value === 'string') return value;
        return null;
    }

    private emptyToNull(value: string | undefined): string | null {
        if (value == null) return null;
        return value.trim().length === 0 ? null : value;
    }

    private asNullableNumber(value: unknown): number | null {
        if (typeof value === 'number' && Number.isFinite(value)) return value;
        if (typeof value === 'string' && value.trim().length > 0) {
            const parsed = Number(value);
            return Number.isFinite(parsed) ? parsed : null;
        }
        return null;
    }

    private asStringArray(value: unknown): string[] {
        if (!Array.isArray(value)) return [];
        return value.filter((item): item is string => typeof item === 'string');
    }

    private asStringRecord(value: unknown): Record<string, string> {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
        const result: Record<string, string> = {};
        Object.entries(value as Record<string, unknown>).forEach(([key, val]) => {
            result[key] = typeof val === 'string' ? val : String(val ?? '');
        });
        return result;
    }
}
