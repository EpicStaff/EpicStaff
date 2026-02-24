import { TableDocument } from "../components/rag-configuration/configuration-table/configuration-table.interface";
import { NaiveRagDocumentConfig } from "../models/naive-rag-document.model";

/**
 * Transforms NaiveRagDocumentConfigs to TableDocuments
 */
export function transformToTableDocuments(documents: NaiveRagDocumentConfig[]): TableDocument[] {
    return documents.map(d => ({ ...d, checked: false }));
}
