import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, input, output } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AuthorshipDetailsSource, JsonEditorComponent } from '@shared/components';
import { Subject } from 'rxjs';

import { PLATFORM_IS_MAC } from '../../../core/services/platform-is-mac.token';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import {
    renderCodeDiffViewWithStubEditor,
    shownCodeDiffLanguages,
    shownCodeDiffs,
} from '../code-diff-view/code-diff-view.testing';
import { DomainDialogComponent, DomainDialogData } from './domain-dialog.component';

// The real editor is Monaco, which jsdom cannot run; the footer is all this spec looks at.
@Component({ selector: 'app-json-editor', template: '' })
class JsonEditorStubComponent {
    readonly jsonData = input('');
    readonly readonly = input(false);
    readonly fullHeight = input(false);
    readonly jsonChange = output<string>();
    readonly validationChange = output<boolean>();
    readonly editorReady = output<unknown>();
}

// Built from local-time parts so the expectation holds in any time zone the tests run in.
const AUTHORSHIP: AuthorshipDetailsSource = {
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: 'https://example.com/avatars/ivan.png' },
    created_at: new Date(2026, 2, 12, 13, 28, 23).toISOString(),
    last_edited_by: { id: 2, display_name: 'Olga Mageria', avatar_url: null },
    last_edited_at: null,
};

let fixture: ComponentFixture<DomainDialogComponent>;

function render(data: DomainDialogData, isPreview: boolean, isMac = false): HTMLElement {
    TestBed.configureTestingModule({
        providers: [
            { provide: DIALOG_DATA, useValue: data },
            {
                provide: DialogRef,
                useValue: {
                    close: vi.fn(),
                    backdropClick: new Subject<MouseEvent>(),
                    keydownEvents: new Subject<KeyboardEvent>(),
                },
            },
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PLATFORM_IS_MAC, useValue: isMac },
            { provide: PermissionsService, useValue: { can: () => true } },
        ],
    });
    TestBed.overrideComponent(DomainDialogComponent, {
        remove: { imports: [JsonEditorComponent] },
        add: { imports: [JsonEditorStubComponent] },
    });
    renderCodeDiffViewWithStubEditor();
    fixture = TestBed.createComponent(DomainDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

const textOf = (element: Element | null): string => element?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

/** Each footer column as the viewer reads it: the label and name on one line, the date and time below. */
const footerColumns = (footer: Element): string[][] =>
    Array.from(footer.querySelectorAll('.authorship-footer__column')).map((column) => [
        textOf(column.querySelector('.authorship-footer__user')),
        textOf(column.querySelector('.authorship-footer__when')),
    ]);

describe('DomainDialogComponent', () => {
    it.each([
        ['an editable flow', false],
        ['a version preview', true],
    ])('shows who created and who last edited the Start node in a footer below the editor, in %s', (_, isPreview) => {
        const host = render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, isPreview);
        const footer = host.querySelector('.dialog-container > .dialog-content + app-authorship-footer');

        expect(footer).not.toBeNull();
        expect(footerColumns(footer!)).toEqual([
            ['Created by Ivan Bohun', 'Mar 12, 2026, 13:28:23'],
            ['Edited by Olga Mageria', '—'],
        ]);
        expect(footer!.querySelector('app-user-avatar')).toBeNull();
    });

    it('shows the variables a restore changes as a JSON diff of the current canvas and the version, not the editor', () => {
        const host = render(
            {
                initialData: { variables: { topic: 'b' } },
                authorship: AUTHORSHIP,
                variablesDiff: { current: '{ "topic": "a" }', version: '{ "topic": "b" }' },
            },
            true
        );

        expect(shownCodeDiffs(fixture.debugElement)).toEqual([
            { current: '{ "topic": "a" }', version: '{ "topic": "b" }' },
        ]);
        expect(shownCodeDiffLanguages(fixture.debugElement)).toEqual(['json']);
        expect(host.querySelector('app-json-editor')).toBeNull();
    });

    it.each([
        { case: 'in a version preview without a diff (Preview tab, unchanged variables)', isPreview: true },
        { case: 'in the live editor', isPreview: false },
    ])('shows the editor $case', ({ isPreview }) => {
        const host = render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, isPreview);

        expect(host.querySelector('app-json-editor')).not.toBeNull();
        expect(shownCodeDiffs(fixture.debugElement)).toEqual([]);
    });

    describe('variable picker key', () => {
        // Monaco's own key codes: the dialog binds its keys with them, and a real editor dispatches by them.
        const CTRL_CMD = 2048; // ⌘ on a Mac, Ctrl elsewhere
        const WIN_CTRL = 256; // ⌃ on a Mac, the Windows key elsewhere
        const SPACE = 10;
        const KEY_I = 39;

        // The cursor sits in the empty `user` array and there is no `context` to pick from yet.
        const STATE = '{ "persistent_variables": { "user": [], "organization": [] } }';
        const CURSOR_IN_USER_ARRAY = STATE.indexOf('[]') + 1;

        afterEach(() => vi.unstubAllGlobals());

        /**
         * Hands the dialog a stand-in Monaco editor and returns the key bindings it holds right now. Only `addAction`
         * exists on it: Monaco's `addCommand` binds for the whole page and is never removed, which broke the
         * suggestion keys in every other code editor once this dialog had been open.
         */
        function openEditor(): Map<number, () => void> {
            vi.stubGlobal('monaco', {
                KeyMod: { CtrlCmd: CTRL_CMD, WinCtrl: WIN_CTRL },
                KeyCode: { Space: SPACE, KeyI: KEY_I },
            });
            const bindings = new Map<number, () => void>();
            const editorElement = document.createElement('div');
            const editor = {
                addAction: (action: { keybindings?: number[]; run: () => void }) => {
                    const keys = action.keybindings ?? [];
                    keys.forEach((keybinding) => bindings.set(keybinding, action.run));
                    return { dispose: () => keys.forEach((keybinding) => bindings.delete(keybinding)) };
                },
                onKeyDown: () => ({ dispose: () => undefined }),
                onDidChangeCursorPosition: () => ({ dispose: () => undefined }),
                getModel: () => ({ getValue: () => STATE, getOffsetAt: () => CURSOR_IN_USER_ARRAY }),
                getPosition: () => ({ lineNumber: 1, column: CURSOR_IN_USER_ARRAY + 1 }),
                getScrolledVisiblePosition: () => ({ left: 0, top: 0, height: 16 }),
                getDomNode: () => editorElement,
            };
            fixture.debugElement
                .query(By.directive(JsonEditorStubComponent))
                .componentInstance.editorReady.emit(editor);
            return bindings;
        }

        function press(bindings: Map<number, () => void>, keybinding: number): string {
            const run = bindings.get(keybinding);
            expect(run, 'nothing is bound to this key').toBeDefined();
            run!();
            fixture.detectChanges();
            return textOf(document.querySelector('app-autocomplete-overlay .no-results'));
        }

        it.each([
            ['Windows and Linux', false, 'Ctrl+Space'],
            ['a Mac', true, '⌘I'],
        ])('is named in the hint above the editor on %s', (_, isMac, key) => {
            const host = render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, false, isMac);

            expect(textOf(host.querySelector('.autocomplete-hint kbd'))).toBe(key);
        });

        it.each([
            ['Ctrl+Space on Windows and Linux', false, CTRL_CMD | SPACE, 'Ctrl+Space'],
            ['Ctrl+I on Windows and Linux', false, CTRL_CMD | KEY_I, 'Ctrl+Space'],
            ['⌃Space on a Mac', true, WIN_CTRL | SPACE, '⌘I'],
            ['⌘I on a Mac', true, CTRL_CMD | KEY_I, '⌘I'],
        ])('opens the picker with %s', (_, isMac, keybinding, shownKey) => {
            render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, false, isMac);

            expect(press(openEditor(), keybinding)).toBe(
                `Define variables inside "context" object first, then use ${shownKey} here to pick them.`
            );
        });

        it('leaves ⌘Space to Spotlight on a Mac', () => {
            render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, false, true);

            expect(openEditor().has(CTRL_CMD | SPACE)).toBe(false);
        });

        it('gives the keys back to other code editors when the dialog closes', () => {
            render({ initialData: {}, authorship: AUTHORSHIP, variablesDiff: null }, false, false);
            const bindings = openEditor();

            fixture.destroy();

            expect([...bindings.keys()]).toEqual([]);
        });
    });
});
