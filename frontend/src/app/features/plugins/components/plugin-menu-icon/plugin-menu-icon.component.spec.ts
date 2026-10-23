import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PluginMenuIconComponent } from './plugin-menu-icon.component';

describe('PluginMenuIconComponent', () => {
    let fixture: ComponentFixture<PluginMenuIconComponent>;

    function render(src: string | null): HTMLElement {
        fixture = TestBed.createComponent(PluginMenuIconComponent);
        fixture.componentRef.setInput('src', src);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    it.each([
        '/api/plugin-public/asg/icons/projects.svg/?v=1.2.0',
        '/api/plugin-public/asg/icons/overview.png/?v=1.0.0-beta.1+build.7',
        '/api/plugin-public/time-sheets/icons/0_week-view.svg/?v=10.0.3-rc.0',
        'data:image/svg+xml;base64,PHN2Zy8+',
        'data:image/png;base64,iVBORw0KGgo=',
    ])('draws %s as a mask in the text colour', (src) => {
        const host = render(src);

        expect(host.style.getPropertyValue('mask-image')).toBe(`url("${src}")`);
        expect(host.classList).toContain('plugin-menu-icon--drawn');
        expect(host.querySelector('.plugin-menu-icon__placeholder')).toBeNull();
        expect(host.getAttribute('aria-hidden')).toBe('true');
    });

    it.each([
        null,
        'https://evil.example.com/icon.svg',
        '//evil.example.com/icon.svg',
        '/api/plugins/available/',
        'javascript:alert(1)',
        'data:text/html;base64,PHN2Zy8+',
        'data:image/svg+xml,<svg onload="alert(1)"/>',
        '/api/plugin-public/asg/icons/a.svg") , url("https://evil.example.com/x',
        '/api/plugin-public/asg/icons/a.svg\\") ',
        // The browser resolves dot segments and their escapes before it fetches: any path of this site.
        '/api/plugin-public/../auth/x/',
        '/api/plugin-public/asg/icons/../../../auth/x/?v=1.0.0',
        '/api/plugin-public/%2e%2e/auth/x/',
        '/api/plugin-public/asg/icons/%2E%2E%2F%2E%2E%2Fauth.svg/?v=1.0.0',
        '/api/plugin-public/asg%2F..%2F..%2Fauth/icons/a.svg/?v=1.0.0',
        // Other public plugin files, and the rest of the API.
        '/api/plugin-public/asg/config/',
        '/api/plugin-public/asg/icon/?v=1.0.0',
        '/api/plugin-public/asg/icons/a.svg/?v=1.0.0&next=/api/auth/',
        '/api/plugin-public/asg/icons/a.gif/?v=1.0.0',
        '/api/plugin-public/asg/icons/a.svg/?v=latest',
        '/api/auth/me/',
    ])('loads nothing from %j and shows a dot instead', (src) => {
        const host = render(src);

        expect(host.style.getPropertyValue('mask-image')).toBe('');
        expect(host.classList).not.toContain('plugin-menu-icon--drawn');
        expect(host.querySelector('.plugin-menu-icon__placeholder')).not.toBeNull();
    });

    it('takes its size from the input', () => {
        fixture = TestBed.createComponent(PluginMenuIconComponent);
        fixture.componentRef.setInput('size', '2rem');
        fixture.detectChanges();

        expect((fixture.nativeElement as HTMLElement).style.getPropertyValue('--plugin-menu-icon-size')).toBe('2rem');
    });
});
