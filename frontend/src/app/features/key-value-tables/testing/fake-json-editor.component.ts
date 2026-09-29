import { afterNextRender, Component, ElementRef, input, output, viewChild } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { JsonEditorComponent } from '@shared/components';
import type { editor as MonacoEditor, IDisposable } from 'monaco-editor';

import { EntryCellEditorComponent } from '../components/key-value-entries-grid/entry-cell-editor.component';

// Monaco's own values for the keys the value editor binds, as the loader puts them on `window.monaco`.
export const FAKE_MONACO = {
    KeyCode: { Enter: 3, Escape: 9, Tab: 2 },
    KeyMod: { CtrlCmd: 2048, Shift: 1024 },
};

const KEY_CODES: Record<string, number> = {
    Enter: FAKE_MONACO.KeyCode.Enter,
    Escape: FAKE_MONACO.KeyCode.Escape,
    Tab: FAKE_MONACO.KeyCode.Tab,
};

interface FakeKeybinding {
    keybinding: number;
    // The editor it is scoped to, as an action's `editorId` precondition; null for a command, which is page-wide.
    editorId: number | null;
    run: () => void;
}

// Monaco's keybinding service is one for the page: every editor's bindings land here.
const keybindings = new Set<FakeKeybinding>();
let nextEditorId = 0;

// Bindings still registered with the page, for checking that an editor took its own with it.
export function liveFakeKeybindings(): number {
    return keybindings.size;
}

/**
 * Stands in for app-json-editor in specs: jsdom cannot load Monaco (the AMD loader never runs). A textarea is the
 * editor's text, and a fake editor dispatches bindings the way Monaco does: a bound key runs the newest binding that
 * applies here and stops there; any other key goes on to the page. As in Monaco, `addCommand` binds for the whole
 * page for good, while `addAction` binds for its own editor until disposed. Key contexts count as true, since no
 * widget or snippet is ever active here. Like the real editor, it opens '' as '{}'.
 */
@Component({
    selector: 'app-json-editor',
    template: `<textarea
        #field
        class="fake-json-editor"
        [value]="jsonData() || '{}'"
        (input)="jsonChange.emit(field.value)"
        (keydown)="onKeydown($event)"
    ></textarea>`,
})
export class FakeJsonEditorComponent {
    readonly jsonData = input('{}');
    readonly title = input('');
    readonly editorHeight = input(200);
    readonly editorOptions = input<MonacoEditor.IStandaloneEditorConstructionOptions>();

    readonly jsonChange = output<string>();
    readonly editorReady = output<MonacoEditor.IStandaloneCodeEditor>();

    private readonly field = viewChild.required<ElementRef<HTMLTextAreaElement>>('field');

    private readonly editorId = ++nextEditorId;

    constructor() {
        // Monaco is up once the view is: the real editor says so asynchronously too, after its loader.
        afterNextRender(() => this.editorReady.emit(this.fakeEditor()));
    }

    protected onKeydown(event: KeyboardEvent): void {
        const keyCode = KEY_CODES[event.key];
        if (keyCode === undefined) return;
        const modifiers =
            (event.ctrlKey || event.metaKey ? FAKE_MONACO.KeyMod.CtrlCmd : 0) |
            (event.shiftKey ? FAKE_MONACO.KeyMod.Shift : 0);
        const binding = [...keybindings]
            .reverse()
            .find(
                (candidate) =>
                    candidate.keybinding === (modifiers | keyCode) &&
                    (candidate.editorId === null || candidate.editorId === this.editorId)
            );
        if (!binding) return;
        event.preventDefault();
        event.stopPropagation();
        binding.run();
    }

    private fakeEditor(): MonacoEditor.IStandaloneCodeEditor {
        const field = this.field().nativeElement;
        const members: Pick<
            MonacoEditor.IStandaloneCodeEditor,
            'addAction' | 'addCommand' | 'focus' | 'getValue' | 'setValue'
        > = {
            addAction: (descriptor) =>
                this.bind(descriptor.keybindings ?? [], this.editorId, () => descriptor.run(editor)),
            addCommand: (keybinding, handler) => {
                this.bind([keybinding], null, () => handler());
                return null;
            },
            focus: () => field.focus(),
            getValue: () => field.value,
            setValue: (value) => (field.value = value),
        };
        // Only the members above are ever used.
        const editor = members as unknown as MonacoEditor.IStandaloneCodeEditor;
        return editor;
    }

    private bind(keys: number[], editorId: number | null, run: () => void): IDisposable {
        const added = keys.map((keybinding) => ({ keybinding, editorId, run }));
        added.forEach((binding) => keybindings.add(binding));
        return { dispose: () => added.forEach((binding) => keybindings.delete(binding)) };
    }
}

// Swaps the real JSON editor for the fake in the value cell editor. Call before creating the component.
export function useFakeJsonEditor(): void {
    TestBed.overrideComponent(EntryCellEditorComponent, {
        remove: { imports: [JsonEditorComponent] },
        add: { imports: [FakeJsonEditorComponent] },
    });
}
