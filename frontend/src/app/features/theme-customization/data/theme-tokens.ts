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
                name: '--color-surface-card',
                label: 'Surface card',
                samples: [{ kind: 'card', label: 'Card', prop: 'background' }],
            },
            {
                name: '--color-surface-contrast',
                label: 'Contrast surface',
                samples: [{ kind: 'surface', label: 'Aa', prop: 'background' }],
            },
            {
                name: '--color-card-background',
                label: 'Card background',
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
                name: '--active-color',
                label: 'Active color',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'link', label: 'Active tab', prop: 'color' },
                ],
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
            {
                name: '--color-text-muted',
                label: 'Muted text',
                samples: [{ kind: 'text', label: 'Aa Muted text', prop: 'color' }],
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
                name: '--color-line',
                label: 'Line',
                samples: [{ kind: 'divider' }],
            },
        ],
    },
    {
        title: 'Statuses & feedback',
        tokens: [
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
            {
                name: '--color-status-info',
                label: 'Status info',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'In review', prop: 'color' },
                ],
            },
            {
                name: '--color-status-warning',
                label: 'Status warning',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Warning', prop: 'color' },
                ],
            },
            {
                name: '--color-status-processing',
                label: 'Status processing',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Processing', prop: 'color' },
                ],
            },
            {
                name: '--color-status-failed',
                label: 'Status failed',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'text', label: 'Failed', prop: 'color' },
                ],
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
        ],
    },
    {
        title: 'Decorative accents',
        tokens: [
            {
                name: '--cyan-500',
                label: 'Cyan accent',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'badge', label: 'Min', prop: 'background' },
                ],
            },
            {
                name: '--violet-500',
                label: 'Violet accent',
                samples: [
                    { kind: 'dot', prop: 'background' },
                    { kind: 'badge', label: 'Max', prop: 'background' },
                ],
            },
        ],
    },
];

export const ALL_THEME_TOKENS: string[] = THEME_TOKEN_GROUPS.flatMap((group) =>
    group.tokens.map((token) => token.name)
);
