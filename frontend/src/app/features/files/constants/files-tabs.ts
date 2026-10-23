/** Child route paths of `/storage`; `FilesListPageComponent` renders the page for the active one. */
export const FILES_TAB = {
    KnowledgeSources: 'knowledge-sources',
    Storage: 'files',
    KeyValueTables: 'key-value-tables',
} as const;

export type FilesTab = (typeof FILES_TAB)[keyof typeof FILES_TAB];
