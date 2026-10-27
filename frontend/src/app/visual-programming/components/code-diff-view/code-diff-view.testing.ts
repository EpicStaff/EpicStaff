import { Component, DebugElement, effect, input, output, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import type { editor as MonacoEditor } from 'monaco-editor';
import { DiffEditorComponent, DiffEditorModel } from 'ngx-monaco-editor-v2';

import { CodeDiffViewComponent } from './code-diff-view.component';

/**
 * Stands in for the Monaco diff editor, which needs a browser runtime the tests do not load. Keeps what it is given
 * and counts its builds the way the real one rebuilds itself: once at the start, then again on every changed input.
 */
// eslint-disable-next-line @angular-eslint/component-selector -- takes the place of the library's own element
@Component({ selector: 'ngx-monaco-diff-editor', template: '' })
export class DiffEditorStubComponent {
    readonly options = input<MonacoEditor.IStandaloneDiffEditorConstructionOptions>({});
    readonly originalModel = input<DiffEditorModel>();
    readonly modifiedModel = input<DiffEditorModel>();
    readonly onInit = output<MonacoEditor.IStandaloneDiffEditor>();

    readonly builds = signal(0);

    constructor() {
        effect(() => {
            this.options();
            this.originalModel();
            this.modifiedModel();
            this.builds.update((count) => count + 1);
        });
    }
}

/** Renders every code diff view with the stand-in diff editor. */
export function renderCodeDiffViewWithStubEditor(): void {
    TestBed.overrideComponent(CodeDiffViewComponent, {
        remove: { imports: [DiffEditorComponent] },
        add: { imports: [DiffEditorStubComponent] },
    });
}

/** The code diffs shown under `root`, as the two codes each diff editor compares. */
export function shownCodeDiffs(root: DebugElement): { current: string | undefined; version: string | undefined }[] {
    return root.queryAll(By.directive(DiffEditorStubComponent)).map((element) => {
        const editor = element.componentInstance as DiffEditorStubComponent;
        return { current: editor.originalModel()?.code, version: editor.modifiedModel()?.code };
    });
}

/** The language each code diff shown under `root` highlights its codes in. */
export function shownCodeDiffLanguages(root: DebugElement): (string | undefined)[] {
    return root
        .queryAll(By.directive(DiffEditorStubComponent))
        .map((element) => (element.componentInstance as DiffEditorStubComponent).modifiedModel()?.language);
}

/**
 * The marks shown around a code (its editor or its diff view) under `root`, each by what a screen reader is told about
 * it (its description), which is also the text of its tooltip.
 */
export function codeMarkDescriptions(root: HTMLElement): string[] {
    return Array.from(root.querySelectorAll('app-diff-field-mark.diff-field-mark--shown'))
        .filter((mark) => mark.querySelector('app-code-editor, app-code-diff-view') !== null)
        .map((mark) => document.getElementById(mark.getAttribute('aria-describedby') ?? '')?.textContent ?? '');
}
