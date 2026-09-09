import { FlowNodeListItem } from '@shared/components';

import { ReviewPythonCode } from '../../../../../core/models/review-item.model';

export interface FlowReviewNode extends FlowNodeListItem {
    key: string;
    fieldKeys: string[];
    codes: ReviewPythonCode[];
    fieldLabels: (string | null)[];
    codeFieldCount: number;
}

export interface CodeTab {
    label: string;
    fieldKey: string;
}

export interface CodeReviewableEntry {
    kind: 'code';
    title: string;
    fieldKey: string;
    code: ReviewPythonCode;
    codeTabs: CodeTab[];
}

export interface McpReviewableEntry {
    kind: 'mcp';
    title: string;
    fieldKey: string;
    name: string;
    transport: string;
}

export type ReviewableEntry = CodeReviewableEntry | McpReviewableEntry;
