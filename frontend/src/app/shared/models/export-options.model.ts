export interface ExportOptions {
    /** Carry the knowledge collections the exported items use, with their files. */
    includeKnowledge: boolean;
}

/** How the export options dialog names what is exported, e.g. `flow` / `flows`. */
export interface ExportEntityLabels {
    singular: string;
    plural: string;
}
