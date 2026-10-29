import { ExcludedExportEntity } from '../models/export-result.model';
import { formatExportExclusionWarning } from './export-exclusion-warning.util';

const TAIL = 'You do not have permission to export these. Re-assign them after import.';

describe('formatExportExclusionWarning', () => {
    const cases: { name: string; excluded: ExcludedExportEntity[]; expected: string }[] = [
        {
            name: 'lists the names of the excluded entities',
            excluded: [{ type: 'AgentDefinition', count: 3, names: ['A', 'B', 'C'] }],
            expected: `Exported without 3 agents (A, B, C). ${TAIL}`,
        },
        {
            name: 'uses the singular for a single entity',
            excluded: [{ type: 'AgentDefinition', count: 1, names: ['A'] }],
            expected: `Exported without 1 agent (A). ${TAIL}`,
        },
        {
            name: 'shows only the count when no names are readable',
            excluded: [{ type: 'AgentDefinition', count: 3, names: [] }],
            expected: `Exported without 3 agents. ${TAIL}`,
        },
        {
            name: 'reports how many names were left out when the list is capped',
            excluded: [{ type: 'AgentDefinition', count: 7, names: ['A', 'B', 'C', 'D', 'E'] }],
            expected: `Exported without 7 agents (A, B, C, D, E +2 more). ${TAIL}`,
        },
        {
            name: 'labels MCP tools',
            excluded: [{ type: 'MCPTool', count: 1, names: ['Search'] }],
            expected: `Exported without 1 MCP tool (Search). ${TAIL}`,
        },
        {
            name: 'labels subflows',
            excluded: [{ type: 'Flow', count: 2, names: [] }],
            expected: `Exported without 2 subflows. ${TAIL}`,
        },
        {
            name: 'joins two types with "and"',
            excluded: [
                { type: 'AgentDefinition', count: 3, names: ['A', 'B', 'C'] },
                { type: 'PythonCodeTool', count: 2, names: [] },
            ],
            expected: `Exported without 3 agents (A, B, C) and 2 Python tools. ${TAIL}`,
        },
        {
            name: 'joins three types with commas and a final "and"',
            excluded: [
                { type: 'AgentDefinition', count: 1, names: ['A'] },
                { type: 'PythonCodeTool', count: 2, names: [] },
                { type: 'Flow', count: 1, names: ['Child'] },
            ],
            expected: `Exported without 1 agent (A), 2 Python tools and 1 subflow (Child). ${TAIL}`,
        },
        {
            name: 'calls an unknown entity type "items"',
            excluded: [{ type: 'Widget', count: 2, names: [] }],
            expected: `Exported without 2 items. ${TAIL}`,
        },
    ];

    it.each(cases)('$name', ({ excluded, expected }) => {
        expect(formatExportExclusionWarning(excluded)).toBe(expected);
    });

    it('returns null when nothing was excluded', () => {
        expect(formatExportExclusionWarning([])).toBeNull();
    });
});
