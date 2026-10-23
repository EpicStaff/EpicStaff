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
