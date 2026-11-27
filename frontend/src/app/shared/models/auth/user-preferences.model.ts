/** The personal settings of the signed-in user, grouped in sections. Each section is saved on its own. */

export interface GeneralPreferences {
    /** IANA zone dates are shown in; `null` follows the browser. */
    readonly display_timezone: string | null;
    /** IANA zone new schedule triggers open with; `null` follows the browser. */
    readonly default_timezone: string | null;
}

export type FlowEdgeStyle = 'orthogonal' | 'adaptive-curve';

/** What the flow editor shows when a flow opens: the whole flow, or the viewport the user left. */
export type FlowOnOpen = 'fit' | 'restore';

export interface FlowEditorPreferences {
    readonly arrow_colors: boolean;
    readonly show_inputs_outputs: boolean;
    readonly edge_style: FlowEdgeStyle;
    readonly always_show_node_numbers: boolean;
    readonly highlight_unused_nodes: boolean;
    readonly show_minimap: boolean;
    readonly on_open: FlowOnOpen;
}

/** The effective preferences: the server's defaults merged with what the user stored. */
export interface UserPreferences {
    readonly general: GeneralPreferences;
    readonly flow_editor: FlowEditorPreferences;
}

export type PreferenceSection = keyof UserPreferences;

/** The same defaults the server applies; used until the profile arrives and for keys it does not send. */
export const DEFAULT_USER_PREFERENCES: UserPreferences = {
    general: {
        display_timezone: null,
        default_timezone: null,
    },
    flow_editor: {
        arrow_colors: true,
        show_inputs_outputs: false,
        edge_style: 'orthogonal',
        always_show_node_numbers: false,
        highlight_unused_nodes: false,
        show_minimap: true,
        on_open: 'fit',
    },
};
