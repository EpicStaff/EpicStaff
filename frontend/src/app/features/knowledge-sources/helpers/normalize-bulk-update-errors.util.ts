import {
    NormalizedDocumentErrors
} from "../components/rag-configuration/configuration-table/configuration-table.interface";
import { UpdateNaiveRagDocumentConfigError } from "../models/naive-rag-document.model";

export function normalizeBulkUpdateErrors(
    errors?: UpdateNaiveRagDocumentConfigError[]
): NormalizedDocumentErrors {
    if (!errors?.length) return {};

    return errors.reduce((acc, e) => {
        acc[e.field] = { reason: e.reason, value: e.value };
        return acc;
    }, {} as NormalizedDocumentErrors);
}
