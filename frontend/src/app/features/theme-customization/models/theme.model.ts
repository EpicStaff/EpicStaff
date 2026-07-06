export interface CustomTheme {
    id: string;
    name: string;
    base: 'dark' | 'light';
    overrides: Record<string, string>;
}

export type ThemeSelection = 'dark' | 'light' | string;
