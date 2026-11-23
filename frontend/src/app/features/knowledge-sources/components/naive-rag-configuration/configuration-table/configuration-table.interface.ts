import { NaiveRagDocumentConfig, UpdateNaiveRagDocumentConfigError } from '../../../models/naive-rag-document.model';

export type DocumentStatusFilter = 'all' | 'issues' | 'not_indexed' | 'indexed';

export interface TableDocument extends NaiveRagDocumentConfig {
    checked: boolean;
    errors?: NormalizedDocumentErrors;
}

/** A document's refused settings by field: its own fields, and any other field the server names. */
export type NormalizedDocumentErrors = {
    [K in keyof TableDocument]?: Partial<UpdateNaiveRagDocumentConfigError>;
} & Record<string, Partial<UpdateNaiveRagDocumentConfigError> | undefined>;
