/** One line of a preview list: what it is, and a short note beside it. */
export interface PluginPreviewItemView {
    /** Unique within its list. */
    key: string;
    name: string;
    detail: string | null;
}

/** The items a list shows, and how many more the server counted but did not send. */
export interface PluginPreviewListView {
    items: PluginPreviewItemView[];
    moreCount: number;
}
