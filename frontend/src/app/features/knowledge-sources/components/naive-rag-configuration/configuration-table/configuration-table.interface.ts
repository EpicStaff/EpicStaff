import { NaiveRagDocumentConfig, UpdateNaiveRagDocumentConfigError } from '../../../models/naive-rag-document.model';

export type DocumentStatusFilter = 'all' | 'issues' | 'not_indexed' | 'indexed';

export interface TableDocument extends NaiveRagDocumentConfig {
    checked: boolean;
    errors?: NormalizedDocumentErrors;
}

export type NormalizedDocumentErrors = {
    [K in keyof TableDocument]?: Partial<UpdateNaiveRagDocumentConfigError>;
};

export type DocFieldChange = {
    documentId: number;
    documentName: string;
    field: keyof NaiveRagDocumentConfig;
    value: string | number | null;
};
