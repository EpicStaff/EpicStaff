/** Child route paths of `/files`; `FilesListPageComponent` renders the page for the active one. */
export const FILES_TAB = {
    KnowledgeSources: 'knowledge-sources',
    Storage: 'storage',
} as const;

export type FilesTab = (typeof FILES_TAB)[keyof typeof FILES_TAB];
