export type TokenPreviewKind =
    | 'button'
    | 'ghost-button'
    | 'text'
    | 'input'
    | 'surface'
    | 'card'
    | 'border-box'
    | 'divider'
    | 'badge'
    | 'dot'
    | 'scrollbar'
    | 'node'
    | 'link'
    | 'backdrop'
    | 'asterisk';

export type TokenPreviewProp = 'background' | 'color' | 'border' | 'thumb';

export interface TokenPreviewSample {
    kind: TokenPreviewKind;
    label?: string;
    hover?: boolean;
    active?: boolean;
    prop?: TokenPreviewProp;
}

export interface ThemeTokenDef {
    name: string;
    label: string;
    samples?: TokenPreviewSample[];
    description?: string;
}

export interface ThemeTokenGroup {
    title: string;
    tokens: ThemeTokenDef[];
}

export const THEME_TOKEN_GROUPS: ThemeTokenGroup[] = [
    {
        title: 'Surfaces',
        tokens: [
            {
                name: '--color-background-body',
                label: 'Body background',
                samples: [{ kind: 'surface', label: 'Aa Page', prop: 'background' }],
            },
            {
                name: '--color-sidenav-background',
                label: 'Sidenav background',
                samples: [{ kind: 'surface', label: 'Sidenav', prop: 'background' }],
            },
            {
                name: '--color-modals-background',
                label: 'Modals background',
                samples: [{ kind: 'card', label: 'Modal', prop: 'background' }],
            },
            {
                name: '--color-backdrop',
                label: 'Dialog backdrop',
                samples: [{ kind: 'backdrop' }],
            },
            {
                name: '--color-flow-card-bg',
                label: 'Flow card background',
                samples: [{ kind: 'card', label: 'Flow', prop: 'background' }],
            },
            {
                name: '--color-surface',
                label: 'Surface',
                samples: [{ kind: 'surface', label: 'Aa', prop: 'background' }],
            },
            {
                name: '--color-surface-hover',
                label: 'Surface hover',
                samples: [{ kind: 'surface', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--color-surface-card',
                label: 'Surface card',
                samples: [{ kind: 'card', label: 'Card', prop: 'background' }],
            },
            {
                name: '--color-drag-drop-active',
                label: 'Drag & drop active',
                description: 'Background highlight when dragging files over a drop zone.',
            },
        ],
    },
    {
        title: 'Accent & buttons',
        tokens: [
            {
                name: '--accent-color',
                label: 'Accent',
                samples: [
                    { kind: 'button', label: 'Button', prop: 'background' },
                    { kind: 'link', label: 'Active link', prop: 'color' },
                ],
            },
            {
                name: '--accent-color-hover',
                label: 'Accent hover',
                samples: [{ kind: 'button', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--accent-color-active',
                label: 'Accent active',
                samples: [{ kind: 'button', label: 'Press me', prop: 'background', active: true }],
            },
            {
                name: '--accent-light',
                label: 'Accent light',
                samples: [{ kind: 'link', label: 'Accent light', prop: 'color' }],
            },
            {
                name: '--accent-dark',
                label: 'Accent dark',
                samples: [{ kind: 'badge', label: 'Accent dark', prop: 'background' }],
            },
            {
                name: '--accent-darker',
                label: 'Accent darker',
                samples: [{ kind: 'badge', label: 'Accent darker', prop: 'background' }],
            },
            {
                name: '--active-color',
                label: 'Active color',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'link', label: 'Active tab', prop: 'color' },
                ],
            },
            {
                name: '--inactive-purple',
                label: 'Inactive accent',
                samples: [{ kind: 'badge', label: 'Inactive', prop: 'background' }],
            },
            {
                name: '--color-required-asterisk',
                label: 'Required asterisk',
                samples: [{ kind: 'asterisk', label: 'Name' }],
            },
            {
                name: '--color-secondary-btn-background',
                label: 'Secondary button background',
                samples: [{ kind: 'button', label: 'Secondary', prop: 'background' }],
            },
            {
                name: '--color-secondary-btn-background-hover',
                label: 'Secondary button background hover',
                samples: [{ kind: 'button', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--color-ghost-btn-hover',
                label: 'Ghost button hover',
                samples: [{ kind: 'ghost-button', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--color-ghost-btn-active',
                label: 'Ghost button active',
                samples: [{ kind: 'ghost-button', label: 'Press me', prop: 'background', active: true }],
            },
            {
                name: '--color-action-btn-background',
                label: 'Action button background',
                samples: [{ kind: 'button', label: 'Action', prop: 'background' }],
            },
            {
                name: '--color-action-btn-background-hover',
                label: 'Action button background hover',
                samples: [{ kind: 'button', label: 'Hover me', prop: 'background', hover: true }],
            },
        ],
    },
    {
        title: 'Text',
        tokens: [
            {
                name: '--color-text-primary',
                label: 'Primary text',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-text-secondary',
                label: 'Secondary text',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-text-tertiary',
                label: 'Tertiary text',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-text-subtle',
                label: 'Subtle text',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-text-primary-hover',
                label: 'Primary text hover',
                samples: [{ kind: 'text', label: 'Aa Hover me', prop: 'color', hover: true }],
            },
            {
                name: '--color-text-disabled',
                label: 'Disabled text',
                samples: [{ kind: 'text', label: 'Aa Disabled', prop: 'color' }],
            },
        ],
    },
    {
        title: 'Forms',
        tokens: [
            {
                name: '--color-input-background',
                label: 'Input background',
                samples: [{ kind: 'input', label: 'Text', prop: 'background' }],
            },
            {
                name: '--color-input-background-hover',
                label: 'Input background hover',
                samples: [{ kind: 'input', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--color-input-border',
                label: 'Input border',
                samples: [{ kind: 'input', label: 'Text', prop: 'border' }],
            },
            {
                name: '--color-input-text-placeholder',
                label: 'Input placeholder',
                samples: [{ kind: 'input', label: 'Placeholder', prop: 'color' }],
            },
        ],
    },
    {
        title: 'Borders & dividers',
        tokens: [
            {
                name: '--color-components-card-border',
                label: 'Card border',
                samples: [{ kind: 'card', label: 'Card', prop: 'border' }],
            },
            {
                name: '--color-components-card-border-disabled',
                label: 'Card border disabled',
                samples: [{ kind: 'card', label: 'Disabled', prop: 'border' }],
            },
            {
                name: '--color-border',
                label: 'Border',
                samples: [{ kind: 'border-box', prop: 'border' }],
            },
            {
                name: '--color-border-disabled',
                label: 'Border disabled',
                samples: [{ kind: 'border-box', prop: 'border' }],
            },
            {
                name: '--color-divider',
                label: 'Divider',
                samples: [{ kind: 'divider' }],
            },
            {
                name: '--color-divider-regular',
                label: 'Divider regular',
                samples: [{ kind: 'divider' }],
            },
            {
                name: '--color-divider-subtle',
                label: 'Divider subtle',
                samples: [{ kind: 'divider' }],
            },
            {
                name: '--color-divider-strong',
                label: 'Divider strong',
                samples: [{ kind: 'divider' }],
            },
        ],
    },
    {
        title: 'Statuses & feedback',
        tokens: [
            {
                name: '--color-error',
                label: 'Error',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Error message', prop: 'color' },
                ],
            },
            {
                name: '--error-color',
                label: 'Error (legacy)',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Error message', prop: 'color' },
                ],
            },
            {
                name: '--red-color',
                label: 'Red',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'link', label: 'Delete', prop: 'color' },
                ],
            },
            {
                name: '--success-color',
                label: 'Success',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Success', prop: 'color' },
                ],
            },
            {
                name: '--color-warning',
                label: 'Warning',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Warning', prop: 'color' },
                ],
            },
            {
                name: '--color-status-error',
                label: 'Status error',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'badge', label: 'Error', prop: 'color' },
                ],
            },
            {
                name: '--color-status-error-subtle',
                label: 'Status error subtle',
                samples: [{ kind: 'badge', label: 'Error', prop: 'background' }],
            },
            {
                name: '--color-status-error-hover',
                label: 'Status error hover',
                samples: [{ kind: 'badge', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--transparent-white-8',
                label: 'White wash 8%',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--transparent-white-4',
                label: 'White wash 4%',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--transparent-green-8',
                label: 'Green wash 8%',
                samples: [{ kind: 'badge', label: 'Success wash', prop: 'background' }],
            },
            {
                name: '--transparent-orange-8',
                label: 'Orange wash 8%',
                samples: [{ kind: 'badge', label: 'Warning wash', prop: 'background' }],
            },
        ],
    },
    {
        title: 'Scrollbar',
        tokens: [
            {
                name: '--color-scrollbar-thumb',
                label: 'Scrollbar thumb',
                samples: [{ kind: 'scrollbar', prop: 'thumb' }],
            },
            {
                name: '--color-scrollbar-thumb-hover',
                label: 'Scrollbar thumb hover',
                samples: [{ kind: 'scrollbar', prop: 'thumb', hover: true }],
            },
            {
                name: '--color-scrollbar-track',
                label: 'Scrollbar track',
                samples: [{ kind: 'scrollbar', prop: 'background' }],
            },
        ],
    },
    {
        title: 'Flow nodes',
        tokens: [
            {
                name: '--color-nodes-background',
                label: 'Node background',
                samples: [{ kind: 'node', label: 'Node', prop: 'background' }],
            },
            {
                name: '--color-nodes-background-translucent',
                label: 'Node background translucent',
                samples: [{ kind: 'backdrop' }],
            },
            {
                name: '--color-nodes-background-disabled',
                label: 'Node background disabled',
                samples: [{ kind: 'node', label: 'Disabled', prop: 'background' }],
            },
            {
                name: '--color-nodes-input-bg',
                label: 'Node input background',
                samples: [{ kind: 'input', label: 'Text', prop: 'background' }],
            },
            {
                name: '--color-nodes-actionbar-bg',
                label: 'Action bar background',
                samples: [{ kind: 'node', label: 'Toolbar', prop: 'background' }],
            },
            {
                name: '--color-nodes-actionbar-border',
                label: 'Action bar border',
                samples: [{ kind: 'node', label: 'Toolbar', prop: 'border' }],
            },
            {
                name: '--color-nodes-sidepanel-bg',
                label: 'Side panel background',
                samples: [{ kind: 'node', label: 'Panel', prop: 'background' }],
            },
            {
                name: '--color-nodes-flow-link',
                label: 'Flow link',
                samples: [{ kind: 'link', label: 'Flow link', prop: 'color' }],
            },
            {
                name: '--color-nodes-flow-link-hover-bg',
                label: 'Flow link hover background',
                samples: [{ kind: 'link', label: 'Hover me', prop: 'background', hover: true }],
            },
        ],
    },
    {
        title: 'Knowledge sources',
        tokens: [
            {
                name: '--color-ks-primary',
                label: 'Primary',
                samples: [{ kind: 'surface', label: 'Aa', prop: 'background' }],
            },
            {
                name: '--color-ks-secondary',
                label: 'Secondary',
                samples: [{ kind: 'text', label: 'Aa Secondary', prop: 'color' }],
            },
            {
                name: '--color-ks-tetriary',
                label: 'Tertiary',
                samples: [{ kind: 'text', label: 'Aa Tertiary', prop: 'color' }],
            },
            {
                name: '--color-ks-quarternary',
                label: 'Quaternary',
                samples: [{ kind: 'surface', label: 'Aa', prop: 'background' }],
            },
            {
                name: '--color-ks-white',
                label: 'White',
                samples: [{ kind: 'surface', label: 'Aa', prop: 'background' }],
            },
            {
                name: '--color-ks-card-background',
                label: 'Card background',
                samples: [{ kind: 'card', label: 'Card', prop: 'background' }],
            },
            {
                name: '--color-ks-card-tag-background',
                label: 'Card tag background',
                samples: [{ kind: 'badge', label: 'Tag', prop: 'background' }],
            },
            {
                name: '--color-ks-background',
                label: 'Background',
                samples: [{ kind: 'surface', label: 'Aa Page', prop: 'background' }],
            },
            {
                name: '--color-ks-button-activated',
                label: 'Button activated',
                samples: [{ kind: 'button', label: 'Active', prop: 'background' }],
            },
            {
                name: '--color-ks-line',
                label: 'Line',
                samples: [{ kind: 'divider' }],
            },
            {
                name: '--color-ks-hover-row',
                label: 'Row hover',
                samples: [{ kind: 'surface', label: 'Hover me', prop: 'background', hover: true }],
            },
            {
                name: '--color-ks-transparent-black-72',
                label: 'Black wash 72%',
                samples: [{ kind: 'backdrop' }],
            },
            {
                name: '--color-ks-transparent-black-60',
                label: 'Black wash 60%',
                samples: [{ kind: 'backdrop' }],
            },
            {
                name: '--color-ks-transparent-black-28',
                label: 'Black wash 28%',
                samples: [{ kind: 'backdrop' }],
            },
            {
                name: '--color-ks-transparent-text-80',
                label: 'Text wash 80%',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-ks-transparent-text-60',
                label: 'Text wash 60%',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-ks-transparent-text-20',
                label: 'Text wash 20%',
                samples: [{ kind: 'text', label: 'Aa Sample text', prop: 'color' }],
            },
            {
                name: '--color-ks-transparent-blue',
                label: 'Blue wash',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--color-ks-transparent-purple',
                label: 'Purple wash',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--color-ks-transparent-yellow',
                label: 'Yellow wash',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--color-ks-transparent-red',
                label: 'Red wash',
                samples: [{ kind: 'badge', label: 'Wash', prop: 'background' }],
            },
            {
                name: '--color-ks-status-blue',
                label: 'Status blue',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'In review', prop: 'color' },
                ],
            },
            {
                name: '--color-ks-status-completed',
                label: 'Status completed',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Completed', prop: 'color' },
                ],
            },
            {
                name: '--color-ks-status-new',
                label: 'Status new',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'New', prop: 'color' },
                ],
            },
            {
                name: '--color-ks-status-warning',
                label: 'Status warning',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Warning', prop: 'color' },
                ],
            },
            {
                name: '--color-ks-status-processing',
                label: 'Status processing',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Processing', prop: 'color' },
                ],
            },
            {
                name: '--color-ks-status-failed',
                label: 'Status failed',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Failed', prop: 'color' },
                ],
            },
        ],
    },
    {
        title: 'Misc',
        tokens: [
            {
                name: '--color-storage-icon',
                label: 'Storage icon',
                description: 'Color of file and folder icons in the storage browser.',
            },
        ],
    },
];

export const ALL_THEME_TOKENS: string[] = THEME_TOKEN_GROUPS.flatMap((group) =>
    group.tokens.map((token) => token.name)
);
