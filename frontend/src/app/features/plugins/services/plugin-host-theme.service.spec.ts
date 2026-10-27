import { TestBed } from '@angular/core/testing';

import { LIGHT_THEME_CLASS, PLUGIN_THEME_TOKENS, PluginHostThemeService } from './plugin-host-theme.service';

describe('PluginHostThemeService', () => {
    afterEach(() => {
        document.documentElement.classList.remove(LIGHT_THEME_CLASS);
        document.body.classList.remove(LIGHT_THEME_CLASS, 'cdk-global-scrollblock');
        document.body.style.removeProperty('--color-background-body');
        document.body.style.removeProperty('--accent-color');
    });

    /** Lets the MutationObserver deliver its records (a microtask). */
    function flushObserver(): Promise<void> {
        return Promise.resolve();
    }

    it('pins the public token names and the EpicStaff variable behind each', () => {
        expect(PLUGIN_THEME_TOKENS).toEqual({
            '--es-color-background': '--color-background-body',
            '--es-color-surface': '--color-surface-card',
            '--es-color-surface-raised': '--color-modals-background',
            '--es-color-sidenav': '--color-sidenav-background',
            '--es-color-text': '--color-text-primary',
            '--es-color-text-secondary': '--color-text-secondary',
            '--es-color-text-tertiary': '--color-text-tertiary',
            '--es-color-text-disabled': '--color-text-disabled',
            '--es-color-accent': '--accent-color',
            '--es-color-accent-hover': '--accent-color-hover',
            '--es-color-accent-active': '--accent-color-active',
            '--es-color-input-background': '--color-input-background',
            '--es-color-input-border': '--color-input-border',
            '--es-color-input-placeholder': '--color-input-text-placeholder',
            '--es-color-border': '--color-border',
            '--es-color-divider': '--color-divider-regular',
            '--es-color-divider-subtle': '--color-divider-subtle',
            '--es-color-success': '--success-color',
            '--es-color-warning': '--color-warning',
            '--es-color-error': '--color-status-error',
            '--es-focus-ring': '--focus-ring',
            '--es-font-family': '--font-family',
        });
    });

    it('reads the tokens EpicStaff defines on body, and leaves out the ones it does not', () => {
        document.body.style.setProperty('--color-background-body', '#1e1f22');
        document.body.style.setProperty('--accent-color', ' #685fff ');

        const theme = TestBed.inject(PluginHostThemeService).theme();

        expect(theme).toEqual({
            mode: 'dark',
            tokens: { '--es-color-background': '#1e1f22', '--es-color-accent': '#685fff' },
        });
    });

    it.each([
        ['body', () => document.body],
        ['html', () => document.documentElement],
    ])('turns light when %s gets the light class, and dark again when it loses it', async (_label, element) => {
        const service = TestBed.inject(PluginHostThemeService);
        expect(service.theme().mode).toBe('dark');

        element().classList.add(LIGHT_THEME_CLASS);
        await flushObserver();
        expect(service.theme().mode).toBe('light');

        element().classList.remove(LIGHT_THEME_CLASS);
        await flushObserver();
        expect(service.theme().mode).toBe('dark');
    });

    it('keeps the same theme object when an unrelated class changes', async () => {
        const service = TestBed.inject(PluginHostThemeService);
        const before = service.theme();

        document.body.classList.add('cdk-global-scrollblock');
        await flushObserver();

        expect(service.theme()).toBe(before);
    });

    it('re-reads the token values on refresh', () => {
        const service = TestBed.inject(PluginHostThemeService);

        document.body.style.setProperty('--color-background-body', '#f8fafc');
        service.refresh();

        expect(service.theme().tokens).toEqual({ '--es-color-background': '#f8fafc' });
    });
});
