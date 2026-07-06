import { DOCUMENT } from '@angular/common';
import { computed, inject, Injectable, signal } from '@angular/core';

import { ThemeService } from '../../../services/theme/theme.service';
import { ALL_THEME_TOKENS } from '../data/theme-tokens';
import { CustomTheme, ThemeSelection } from '../models/theme.model';

const THEMES_STORAGE_KEY = 'epicstaff.customThemes';
const SELECTION_STORAGE_KEY = 'epicstaff.themeSelection';

@Injectable({
    providedIn: 'root',
})
export class CustomThemeService {
    private readonly themeService = inject(ThemeService);
    private readonly document = inject(DOCUMENT);

    private readonly _themes = signal<CustomTheme[]>([]);
    private readonly _selection = signal<ThemeSelection>('dark');

    readonly themes = this._themes.asReadonly();
    readonly selection = this._selection.asReadonly();

    readonly activeCustomTheme = computed<CustomTheme | null>(() => {
        const selection = this._selection();
        if (selection === 'dark' || selection === 'light') return null;
        return this._themes().find((theme) => theme.id === selection) ?? null;
    });

    constructor() {
        this.load();
        this.apply();
    }

    select(selection: ThemeSelection): void {
        if (selection !== 'dark' && selection !== 'light' && !this._themes().some((t) => t.id === selection)) {
            selection = 'dark';
        }
        this._selection.set(selection);
        this.persist();
        this.apply();
    }

    createTheme(name: string, base: 'dark' | 'light'): CustomTheme {
        const theme: CustomTheme = {
            id: crypto.randomUUID(),
            name,
            base,
            overrides: {},
        };
        this._themes.update((themes) => [...themes, theme]);
        this.persist();
        return theme;
    }

    renameTheme(id: string, name: string): void {
        this.updateTheme(id, (theme) => ({ ...theme, name }));
    }

    setBase(id: string, base: 'dark' | 'light'): void {
        this.updateTheme(id, (theme) => ({ ...theme, base }));
    }

    deleteTheme(id: string): void {
        const deleted = this._themes().find((theme) => theme.id === id);
        this._themes.update((themes) => themes.filter((theme) => theme.id !== id));
        if (this._selection() === id) {
            this._selection.set(deleted?.base ?? 'dark');
        }
        this.persist();
        this.apply();
    }

    setOverride(id: string, token: string, value: string): void {
        this.updateTheme(id, (theme) => ({
            ...theme,
            overrides: { ...theme.overrides, [token]: value },
        }));
    }

    removeOverride(id: string, token: string): void {
        this.updateTheme(id, (theme) => {
            const overrides = { ...theme.overrides };
            delete overrides[token];
            return { ...theme, overrides };
        });
    }

    clearOverrides(id: string): void {
        this.updateTheme(id, (theme) => ({ ...theme, overrides: {} }));
    }

    private updateTheme(id: string, mutate: (theme: CustomTheme) => CustomTheme): void {
        this._themes.update((themes) => themes.map((theme) => (theme.id === id ? mutate(theme) : theme)));
        this.persist();
        if (this._selection() === id) {
            this.apply();
        }
    }

    private apply(): void {
        const active = this.activeCustomTheme();
        const isDark = active ? active.base === 'dark' : this._selection() !== 'light';
        this.themeService.setTheme(isDark);

        const rootStyle = this.document.documentElement.style;
        for (const token of ALL_THEME_TOKENS) {
            rootStyle.removeProperty(token);
        }
        if (active) {
            for (const [token, value] of Object.entries(active.overrides)) {
                rootStyle.setProperty(token, value);
            }
        }
    }

    private load(): void {
        try {
            const rawThemes = localStorage.getItem(THEMES_STORAGE_KEY);
            if (rawThemes) {
                const parsed = JSON.parse(rawThemes);
                if (Array.isArray(parsed)) this._themes.set(parsed);
            }
        } catch (error) {
            console.error('Failed to load custom themes', error);
        }

        const savedSelection = localStorage.getItem(SELECTION_STORAGE_KEY);
        if (savedSelection) {
            const isValid =
                savedSelection === 'dark' ||
                savedSelection === 'light' ||
                this._themes().some((theme) => theme.id === savedSelection);
            this._selection.set(isValid ? savedSelection : 'dark');
        } else {
            this._selection.set(this.themeService.getCurrentTheme() ? 'dark' : 'light');
        }
    }

    private persist(): void {
        localStorage.setItem(THEMES_STORAGE_KEY, JSON.stringify(this._themes()));
        localStorage.setItem(SELECTION_STORAGE_KEY, this._selection());
    }
}
