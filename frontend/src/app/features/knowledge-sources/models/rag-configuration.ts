import { IndexingDocumentInfo } from '../helpers/get-indexing-confirmation-data.util';

export interface RagConfiguration {
    getConfigurationData(): unknown;
    getDocumentConfigIds(): number[];
    getIndexingDocuments(): IndexingDocumentInfo[];
}
