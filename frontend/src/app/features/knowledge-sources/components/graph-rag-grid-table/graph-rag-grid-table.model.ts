export interface GraphGridColumnDef {
    key: string;
    label?: string;
    width?: string;
    /** End-pinned columns stay fixed on the right while the grid scrolls horizontally. */
    pinned?: 'end';
    /**
     * Render this column as a row-level icon button instead of a value cell. Clicking it (or activating
     * the cell via Enter/Space) emits `actionClick` carrying `name` and the row. The column has no header.
     */
    action?: GraphGridActionDef;
}

export interface GraphGridActionDef {
    name: string;
    icon: string;
    tooltip?: string;
}

/** Payload of the grid's `actionClick`: which action's button was pressed, on which row. */
export interface GraphGridActionEvent {
    action: string;
    row: Record<string, unknown>;
}
