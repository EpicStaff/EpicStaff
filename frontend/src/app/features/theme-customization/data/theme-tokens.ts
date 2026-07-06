export interface ThemeTokenDef {
    name: string;
    label: string;
}

export interface ThemeTokenGroup {
    title: string;
    tokens: ThemeTokenDef[];
}

export const THEME_TOKEN_GROUPS: ThemeTokenGroup[] = [
    {
        title: 'Surfaces',
        tokens: [
            { name: '--color-background-body', label: 'Body background' },
            { name: '--color-sidenav-background', label: 'Sidenav background' },
            { name: '--color-modals-background', label: 'Modals background' },
            { name: '--color-backdrop', label: 'Dialog backdrop' },
            { name: '--color-flow-card-bg', label: 'Flow card background' },
            { name: '--color-surface', label: 'Surface' },
            { name: '--color-surface-hover', label: 'Surface hover' },
            { name: '--color-surface-card', label: 'Surface card' },
            { name: '--color-drag-drop-active', label: 'Drag & drop active' },
        ],
    },
    {
        title: 'Accent & buttons',
        tokens: [
            { name: '--accent-color', label: 'Accent' },
            { name: '--accent-color-hover', label: 'Accent hover' },
            { name: '--accent-color-active', label: 'Accent active' },
            { name: '--accent-light', label: 'Accent light' },
            { name: '--accent-dark', label: 'Accent dark' },
            { name: '--accent-darker', label: 'Accent darker' },
            { name: '--active-color', label: 'Active color' },
            { name: '--inactive-purple', label: 'Inactive accent' },
            { name: '--color-required-asterisk', label: 'Required asterisk' },
            { name: '--color-secondary-btn-background', label: 'Secondary button background' },
            { name: '--color-secondary-btn-background-hover', label: 'Secondary button background hover' },
            { name: '--color-ghost-btn-hover', label: 'Ghost button hover' },
            { name: '--color-ghost-btn-active', label: 'Ghost button active' },
            { name: '--color-action-btn-background', label: 'Action button background' },
            { name: '--color-action-btn-background-hover', label: 'Action button background hover' },
        ],
    },
    {
        title: 'Text',
        tokens: [
            { name: '--color-text-primary', label: 'Primary text' },
            { name: '--color-text-secondary', label: 'Secondary text' },
            { name: '--color-text-tertiary', label: 'Tertiary text' },
            { name: '--color-text-subtle', label: 'Subtle text' },
            { name: '--color-text-primary-hover', label: 'Primary text hover' },
            { name: '--color-text-disabled', label: 'Disabled text' },
        ],
    },
    {
        title: 'Forms',
        tokens: [
            { name: '--color-input-background', label: 'Input background' },
            { name: '--color-input-background-hover', label: 'Input background hover' },
            { name: '--color-input-border', label: 'Input border' },
            { name: '--color-input-text-placeholder', label: 'Input placeholder' },
        ],
    },
    {
        title: 'Borders & dividers',
        tokens: [
            { name: '--color-components-card-border', label: 'Card border' },
            { name: '--color-components-card-border-disabled', label: 'Card border disabled' },
            { name: '--color-border', label: 'Border' },
            { name: '--color-border-disabled', label: 'Border disabled' },
            { name: '--color-divider', label: 'Divider' },
            { name: '--color-divider-regular', label: 'Divider regular' },
            { name: '--color-divider-subtle', label: 'Divider subtle' },
            { name: '--color-divider-strong', label: 'Divider strong' },
        ],
    },
    {
        title: 'Statuses & feedback',
        tokens: [
            { name: '--color-error', label: 'Error' },
            { name: '--error-color', label: 'Error (legacy)' },
            { name: '--red-color', label: 'Red' },
            { name: '--success-color', label: 'Success' },
            { name: '--color-warning', label: 'Warning' },
            { name: '--color-status-error', label: 'Status error' },
            { name: '--color-status-error-subtle', label: 'Status error subtle' },
            { name: '--color-status-error-hover', label: 'Status error hover' },
            { name: '--transparent-white-8', label: 'White wash 8%' },
            { name: '--transparent-white-4', label: 'White wash 4%' },
            { name: '--transparent-green-8', label: 'Green wash 8%' },
            { name: '--transparent-orange-8', label: 'Orange wash 8%' },
        ],
    },
    {
        title: 'Scrollbar',
        tokens: [
            { name: '--color-scrollbar-thumb', label: 'Scrollbar thumb' },
            { name: '--color-scrollbar-thumb-hover', label: 'Scrollbar thumb hover' },
            { name: '--color-scrollbar-track', label: 'Scrollbar track' },
        ],
    },
    {
        title: 'Flow nodes',
        tokens: [
            { name: '--color-nodes-background', label: 'Node background' },
            { name: '--color-nodes-background-translucent', label: 'Node background translucent' },
            { name: '--color-nodes-background-disabled', label: 'Node background disabled' },
            { name: '--color-nodes-input-bg', label: 'Node input background' },
            { name: '--color-nodes-actionbar-bg', label: 'Action bar background' },
            { name: '--color-nodes-actionbar-border', label: 'Action bar border' },
            { name: '--color-nodes-sidepanel-bg', label: 'Side panel background' },
            { name: '--color-nodes-flow-link', label: 'Flow link' },
            { name: '--color-nodes-flow-link-hover-bg', label: 'Flow link hover background' },
        ],
    },
    {
        title: 'Knowledge sources',
        tokens: [
            { name: '--color-ks-primary', label: 'Primary' },
            { name: '--color-ks-secondary', label: 'Secondary' },
            { name: '--color-ks-tetriary', label: 'Tertiary' },
            { name: '--color-ks-quarternary', label: 'Quaternary' },
            { name: '--color-ks-white', label: 'White' },
            { name: '--color-ks-card-background', label: 'Card background' },
            { name: '--color-ks-card-tag-background', label: 'Card tag background' },
            { name: '--color-ks-background', label: 'Background' },
            { name: '--color-ks-button-activated', label: 'Button activated' },
            { name: '--color-ks-line', label: 'Line' },
            { name: '--color-ks-hover-row', label: 'Row hover' },
            { name: '--color-ks-transparent-black-72', label: 'Black wash 72%' },
            { name: '--color-ks-transparent-black-60', label: 'Black wash 60%' },
            { name: '--color-ks-transparent-black-28', label: 'Black wash 28%' },
            { name: '--color-ks-transparent-text-80', label: 'Text wash 80%' },
            { name: '--color-ks-transparent-text-60', label: 'Text wash 60%' },
            { name: '--color-ks-transparent-text-20', label: 'Text wash 20%' },
            { name: '--color-ks-transparent-blue', label: 'Blue wash' },
            { name: '--color-ks-transparent-purple', label: 'Purple wash' },
            { name: '--color-ks-transparent-yellow', label: 'Yellow wash' },
            { name: '--color-ks-transparent-red', label: 'Red wash' },
            { name: '--color-ks-status-blue', label: 'Status blue' },
            { name: '--color-ks-status-completed', label: 'Status completed' },
            { name: '--color-ks-status-new', label: 'Status new' },
            { name: '--color-ks-status-warning', label: 'Status warning' },
            { name: '--color-ks-status-processing', label: 'Status processing' },
            { name: '--color-ks-status-failed', label: 'Status failed' },
        ],
    },
    {
        title: 'Misc',
        tokens: [{ name: '--color-storage-icon', label: 'Storage icon' }],
    },
];

export const ALL_THEME_TOKENS: string[] = THEME_TOKEN_GROUPS.flatMap((group) =>
    group.tokens.map((token) => token.name)
);
