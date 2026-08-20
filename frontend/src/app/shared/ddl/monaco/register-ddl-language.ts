import type * as monaco from 'monaco-editor';

import { compile } from '../core/index';
import { type CompletionItem, completions, describeClass } from '../core/service';
import { DDL_LANGUAGE_CONFIGURATION, DDL_LANGUAGE_ID, DDL_MONARCH_LANGUAGE } from './ddl-language';

/**
 * Registers the DDL language, its Monarch tokenizer, and its completion
 * provider with a live Monaco instance.
 *
 * `monaco-editor` is never imported as a value in this module (only as a
 * type, via `typeof import('monaco-editor')`) because the `monaco` global
 * does not exist until `ngx-monaco-editor-v2` lazily loads it. Callers must
 * pass in the runtime namespace obtained from the loaded global — see
 * `DdlEditorComponent.onEditorInit`.
 *
 * Idempotent: safe to call from every editor instance's init callback.
 * Re-registering would duplicate the completion provider (and therefore
 * duplicate every suggestion), so registration only ever runs once per page.
 */
let isDdlLanguageRegistered = false;

export function ensureDdlLanguageRegistered(monacoNs: typeof import('monaco-editor')): void {
    if (isDdlLanguageRegistered) {
        return;
    }
    isDdlLanguageRegistered = true;

    if (!monacoNs.languages.getLanguages().some((language) => language.id === DDL_LANGUAGE_ID)) {
        monacoNs.languages.register({ id: DDL_LANGUAGE_ID });
    }
    monacoNs.languages.setMonarchTokensProvider(DDL_LANGUAGE_ID, DDL_MONARCH_LANGUAGE);
    monacoNs.languages.setLanguageConfiguration(DDL_LANGUAGE_ID, DDL_LANGUAGE_CONFIGURATION);
    monacoNs.languages.registerCompletionItemProvider(DDL_LANGUAGE_ID, createCompletionItemProvider(monacoNs));
}

function createCompletionItemProvider(
    monacoNs: typeof import('monaco-editor')
): monaco.languages.CompletionItemProvider {
    return {
        provideCompletionItems: (model, position) => provideCompletionItems(model, position, monacoNs),
    };
}

function provideCompletionItems(
    model: monaco.editor.ITextModel,
    position: monaco.Position,
    monacoNs: typeof import('monaco-editor')
): monaco.languages.CompletionList {
    // Recompiling the model text per keystroke is fine at this document size.
    const schema = compile(model.getValue());
    const lineTextBeforeCursor = model.getLineContent(position.lineNumber).slice(0, position.column - 1);
    const word = model.getWordUntilPosition(position);
    const range: monaco.IRange = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
    };

    const suggestions = completions(schema, lineTextBeforeCursor).map((item) =>
        toMonacoCompletionItem(
            item,
            range,
            monacoNs,
            item.kind === 'class' ? describeClass(schema, item.label) : undefined
        )
    );
    return { suggestions };
}

function toMonacoCompletionItem(
    item: CompletionItem,
    range: monaco.IRange,
    monacoNs: typeof import('monaco-editor'),
    documentation: string | undefined
): monaco.languages.CompletionItem {
    return {
        label: item.label,
        kind: toMonacoCompletionItemKind(item.kind, monacoNs),
        detail: item.detail,
        documentation,
        insertText: item.label,
        range,
    };
}

function toMonacoCompletionItemKind(
    kind: CompletionItem['kind'],
    monacoNs: typeof import('monaco-editor')
): monaco.languages.CompletionItemKind {
    switch (kind) {
        case 'class':
            return monacoNs.languages.CompletionItemKind.Class;
        case 'primitive':
            return monacoNs.languages.CompletionItemKind.Keyword;
    }
}
