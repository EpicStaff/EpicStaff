import { DOCUMENT, NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, HostListener, inject, signal } from '@angular/core';
import { ColorEvent } from 'ngx-color';
import { ColorChromeModule } from 'ngx-color/chrome';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { TokenPreviewComponent } from '../../components/token-preview/token-preview.component';
import { THEME_TOKEN_GROUPS } from '../../data/theme-tokens';
import { CustomTheme } from '../../models/theme.model';
import { CustomThemeService } from '../../services/custom-theme.service';

const DARK_PREVIEW = ['#212325', '#27272b', '#685fff', '#d9d9de'];
const LIGHT_PREVIEW = ['#f8fafc', '#ffffff', '#685fff', '#1e293b'];

@Component({
    selector: 'app-appearance-page',
    standalone: true,
    imports: [NgStyle, AppSvgIconComponent, ColorChromeModule, TokenPreviewComponent],
    templateUrl: './appearance-page.component.html',
    styleUrls: ['./appearance-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppearancePageComponent {
    private readonly customThemeService = inject(CustomThemeService);
    private readonly document = inject(DOCUMENT);

    readonly groups = THEME_TOKEN_GROUPS;
    readonly darkPreview = DARK_PREVIEW;
    readonly lightPreview = LIGHT_PREVIEW;

    readonly themes = this.customThemeService.themes;
    readonly selection = this.customThemeService.selection;
    readonly activeCustomTheme = this.customThemeService.activeCustomTheme;

    readonly computedValues = signal<Record<string, string>>({});
    readonly pickerToken = signal<string | null>(null);
    readonly pickerStyle = signal<Record<string, string>>({});

    readonly pickerColor = computed(() => {
        const token = this.pickerToken();
        const theme = this.activeCustomTheme();
        if (!token || !theme) return '#000000';
        return theme.overrides[token] ?? this.computedValues()[token] ?? '#000000';
    });

    constructor() {
        this.refreshComputedValues();
    }

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: MouseEvent): void {
        if (!this.pickerToken()) return;
        const target = event.target as HTMLElement;
        if (!target.closest('.appearance__picker')) {
            this.pickerToken.set(null);
        }
    }

    select(selection: string): void {
        this.pickerToken.set(null);
        this.customThemeService.select(selection);
        this.refreshComputedValues();
    }

    createTheme(): void {
        const base = this.activeCustomTheme()?.base ?? (this.selection() === 'light' ? 'light' : 'dark');
        const theme = this.customThemeService.createTheme(`Custom theme ${this.themes().length + 1}`, base);
        this.select(theme.id);
    }

    deleteTheme(theme: CustomTheme, event: MouseEvent): void {
        event.stopPropagation();
        if (!window.confirm(`Delete theme "${theme.name}"?`)) return;
        this.pickerToken.set(null);
        this.customThemeService.deleteTheme(theme.id);
        this.refreshComputedValues();
    }

    rename(id: string, event: Event): void {
        const name = (event.target as HTMLInputElement).value.trim();
        if (name) this.customThemeService.renameTheme(id, name);
    }

    setBase(id: string, base: 'dark' | 'light'): void {
        this.customThemeService.setBase(id, base);
        this.refreshComputedValues();
    }

    resetAll(id: string): void {
        this.customThemeService.clearOverrides(id);
        this.refreshComputedValues();
    }

    resetToken(id: string, token: string): void {
        this.customThemeService.removeOverride(id, token);
        this.refreshComputedValues();
    }

    isOverridden(theme: CustomTheme, token: string): boolean {
        return token in theme.overrides;
    }

    effectiveValue(theme: CustomTheme, token: string): string {
        return theme.overrides[token] ?? this.computedValues()[token] ?? '';
    }

    previewFor(theme: CustomTheme): string[] {
        const base = theme.base === 'light' ? LIGHT_PREVIEW : DARK_PREVIEW;
        return [
            theme.overrides['--color-background-body'] ?? base[0],
            theme.overrides['--color-surface-card'] ?? base[1],
            theme.overrides['--accent-color'] ?? base[2],
            theme.overrides['--color-text-primary'] ?? base[3],
        ];
    }

    openPicker(token: string, event: MouseEvent): void {
        event.stopPropagation();
        if (this.pickerToken() === token) {
            this.pickerToken.set(null);
            return;
        }
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        const pickerHeight = 260;
        const pickerWidth = 228;
        const openUpward = window.innerHeight - rect.bottom < pickerHeight + 12;
        const left = Math.max(12, Math.min(rect.right - pickerWidth, window.innerWidth - pickerWidth - 12));
        this.pickerStyle.set(
            openUpward
                ? { bottom: `${window.innerHeight - rect.top + 6}px`, left: `${left}px` }
                : { top: `${rect.bottom + 6}px`, left: `${left}px` }
        );
        this.pickerToken.set(token);
    }

    onColorChange(event: ColorEvent): void {
        const token = this.pickerToken();
        const theme = this.activeCustomTheme();
        if (!token || !theme) return;
        const { r, g, b, a } = event.color.rgb;
        this.customThemeService.setOverride(theme.id, token, `rgba(${r}, ${g}, ${b}, ${a ?? 1})`);
    }

    private refreshComputedValues(): void {
        const styles = getComputedStyle(this.document.documentElement);
        const values: Record<string, string> = {};
        for (const group of THEME_TOKEN_GROUPS) {
            for (const token of group.tokens) {
                values[token.name] = styles.getPropertyValue(token.name).trim();
            }
        }
        this.computedValues.set(values);
    }
}
