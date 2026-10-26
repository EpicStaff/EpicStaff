import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import type { editor as MonacoEditor } from 'monaco-editor';

import { CodeDiffViewComponent } from './code-diff-view.component';
import { DiffEditorStubComponent, renderCodeDiffViewWithStubEditor } from './code-diff-view.testing';

/** A panel showing one code change; it hands the view a new change object whenever it is told to. */
@Component({
    imports: [CodeDiffViewComponent],
    template: `<app-code-diff-view
        [current]="change().current"
        [version]="change().version"
    />`,
})
class PanelComponent {
    readonly change = signal({ current: 'a = 1\n', version: 'a = 2\n' });
}

let fixture: ComponentFixture<PanelComponent>;

function render(): void {
    renderCodeDiffViewWithStubEditor();
    fixture = TestBed.createComponent(PanelComponent);
    fixture.detectChanges();
}

function show(current: string, version: string): void {
    fixture.componentInstance.change.set({ current, version });
    fixture.detectChanges();
}

const diffEditor = (): DiffEditorStubComponent =>
    fixture.debugElement.query(By.directive(DiffEditorStubComponent)).componentInstance;

describe('CodeDiffViewComponent', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('compares the current canvas code (original) with the version code (modified), as Python', () => {
        render();

        expect(diffEditor().originalModel()).toEqual({ code: 'a = 1\n', language: 'python' });
        expect(diffEditor().modifiedModel()).toEqual({ code: 'a = 2\n', language: 'python' });
    });

    it('shows an inline, read-only diff that keeps whitespace changes and folds unchanged blocks', () => {
        render();

        expect(diffEditor().options()).toMatchObject({
            renderSideBySide: false,
            useInlineViewWhenSpaceIsLimited: false,
            readOnly: true,
            originalEditable: false,
            ignoreTrimWhitespace: false,
            hideUnchangedRegions: { enabled: true },
            theme: 'vs-dark',
        });
    });

    it('builds the editor again only when one of the two codes changes', () => {
        render();
        expect(diffEditor().builds()).toBe(1);

        // The panel hands over a new change with the same codes, e.g. after an unrelated field changed.
        show('a = 1\n', 'a = 2\n');
        expect(diffEditor().builds()).toBe(1);

        show('a = 1\n', 'a = 3\n');
        expect(diffEditor().builds()).toBe(2);
        expect(diffEditor().modifiedModel()?.code).toBe('a = 3\n');
    });

    /** Replaces the browser's ResizeObserver: what each one is told to call on a resize, and which were stopped. */
    function fakeResizeObservers(): { resized: (() => void)[]; disconnected: () => number } {
        const resized: (() => void)[] = [];
        let disconnected = 0;
        vi.stubGlobal(
            'ResizeObserver',
            class {
                constructor(callback: () => void) {
                    resized.push(callback);
                }
                observe(): void {}
                disconnect(): void {
                    disconnected++;
                }
            }
        );
        return { resized, disconnected: () => disconnected };
    }

    it('lays the editor out again when the view is resized, also after a rebuild', () => {
        const { resized } = fakeResizeObservers();
        render();
        const firstEditor = { layout: vi.fn() };
        const rebuiltEditor = { layout: vi.fn() };

        diffEditor().onInit.emit(firstEditor as unknown as MonacoEditor.IStandaloneDiffEditor);
        diffEditor().onInit.emit(rebuiltEditor as unknown as MonacoEditor.IStandaloneDiffEditor);
        resized.forEach((callback) => callback());

        expect(resized).toHaveLength(1);
        expect(rebuiltEditor.layout).toHaveBeenCalledTimes(1);
        expect(firstEditor.layout).not.toHaveBeenCalled();
    });

    it('stops watching its size when it is removed', () => {
        const { disconnected } = fakeResizeObservers();
        render();
        diffEditor().onInit.emit({ layout: vi.fn() } as unknown as MonacoEditor.IStandaloneDiffEditor);

        fixture.destroy();

        expect(disconnected()).toBe(1);
    });
});
