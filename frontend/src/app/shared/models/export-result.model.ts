export interface ExcludedExportEntity {
    type: string;
    count: number;
    names: string[];
}

export interface ExportResult {
    blob: Blob;
    excluded: ExcludedExportEntity[];
}
