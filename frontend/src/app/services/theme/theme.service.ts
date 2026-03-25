import { Injectable, Renderer2, RendererFactory2 } from '@angular/core';
import { Inject } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { BehaviorSubject } from 'rxjs';

@Injectable({
    providedIn: 'root',
})
export class ThemeService {
    private renderer: Renderer2;
    private isDarkMode = new BehaviorSubject<boolean>(true); // Default to dark mode

    public isDarkMode$ = this.isDarkMode.asObservable();

    constructor(
        private rendererFactory: RendererFactory2,
        @Inject(DOCUMENT) private document: Document
    ) {
        this.renderer = this.rendererFactory.createRenderer(null, null);

        // Initialize theme from localStorage or default to dark
        const savedTheme = localStorage.getItem('theme');
        const isDark = savedTheme ? savedTheme === 'dark' : true;
        this.setTheme(isDark);
    }

    public toggleTheme(): void {
        const newTheme = !this.isDarkMode.value;
        this.setTheme(newTheme);
    }

    public setTheme(isDark: boolean): void {
        this.isDarkMode.next(isDark);

        // Save to localStorage
        localStorage.setItem('theme', isDark ? 'dark' : 'light');

        // Update document class based on app.config.ts darkModeSelector
        if (isDark) {
            this.renderer.addClass(
                this.document.documentElement,
                'my-app-dark'
            );
            this.renderer.removeClass(
                this.document.documentElement,
                'my-app-light'
            );
        } else {
            this.renderer.addClass(
                this.document.documentElement,
                'my-app-light'
            );
            this.renderer.removeClass(
                this.document.documentElement,
                'my-app-dark'
            );
        }
    }

    public getCurrentTheme(): boolean {
        return this.isDarkMode.value;
    }
}
