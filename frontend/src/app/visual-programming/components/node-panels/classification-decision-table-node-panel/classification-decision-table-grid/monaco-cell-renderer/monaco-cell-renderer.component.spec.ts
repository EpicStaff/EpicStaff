import { TestBed } from '@angular/core/testing';
import { ICellRendererParams } from 'ag-grid-community';

import { MonacoCellRendererComponent } from './monaco-cell-renderer.component';

interface TestWindow {
    monaco?: { editor?: { colorize: (text: string) => Promise<string>; setTheme: () => void } };
}

const testWindow = window as unknown as TestWindow;

/**
 * Monaco's `colorize` as the real one shapes its output: each line a `<span>` of
 * token spans, followed by `<br/>` (monaco-editor `colorizer.js`). The tokens are
 * not what is under test, so the whole line is one token here.
 */
function fakeColorize(text: string): Promise<string> {
    const lines = text.split('\n').map((line) => `<span><span class="mtk1">${line}</span></span><br/>`);
    return Promise.resolve(lines.join(''));
}

async function render(value: string): Promise<HTMLElement> {
    const fixture = TestBed.createComponent(MonacoCellRendererComponent);
    fixture.componentInstance.agInit({ value } as ICellRendererParams);
    fixture.detectChanges();
    // The loader and `colorize` both settle on promises.
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    fixture.detectChanges();
    return fixture.nativeElement;
}

describe('MonacoCellRendererComponent', () => {
    beforeEach(() => {
        testWindow.monaco = { editor: { colorize: fakeColorize, setTheme: () => undefined } };
    });

    afterEach(() => {
        delete testWindow.monaco;
    });

    it.each([
        ['a multi-line value: its first line and the marker', 'seed_text = "a"\nmarker = "b"', 'seed_text = "a" …'],
        ['a single-line value as it is', 'seed_text = "a"', 'seed_text = "a"'],
    ])('shows %s on one line', async (_case, value, shown) => {
        const element = await render(value);

        const code = element.querySelector('.colorized-code');
        expect(code?.textContent).toBe(shown);
        expect(code?.querySelector('br')).toBeNull();
    });
});
