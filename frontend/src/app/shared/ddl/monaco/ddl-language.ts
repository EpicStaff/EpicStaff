import type * as monaco from 'monaco-editor';

/**
 * Monaco language id for the DDL schema language. Registered lazily the first
 * time an editor initializes — see {@link ../monaco/register-ddl-language.ts}.
 */
export const DDL_LANGUAGE_ID = 'epicstaff-ddl';

const DDL_KEYWORDS = ['class', 'domain', 'is', 'a', 'an'];

/** The 7 built-in scalar type names, kept in sync with `core/ast.ts` PRIMITIVES. */
const DDL_PRIMITIVE_TYPES = ['Int', 'Float', 'Decimal', 'String', 'Bool', 'Date', 'DateTime'];

/** Monarch tokenizer for the DDL language. Monarch is purely lexical — it
 * cannot tell a class reference from an unknown identifier, so both render as
 * plain identifiers; real diagnostics come from {@link diagnosticsToMarkers}. */
export const DDL_MONARCH_LANGUAGE: monaco.languages.IMonarchLanguage = {
    defaultToken: '',
    tokenPostfix: '.ddl',
    keywords: DDL_KEYWORDS,
    primitives: DDL_PRIMITIVE_TYPES,
    brackets: [{ token: 'delimiter.square', open: '[', close: ']' }],
    tokenizer: {
        root: [
            [/#.*$/, 'comment'],
            [
                /[A-Za-z_][A-Za-z0-9_]*/,
                {
                    cases: {
                        '@keywords': 'keyword',
                        '@primitives': 'type.primitive',
                        '@default': 'identifier',
                    },
                },
            ],
            [/"([^"\\]|\\.)*"/, 'string'],
            [/"([^"\\]|\\.)*$/, 'string.invalid'],
            [/-?\d+\.\d+/, 'number.float'],
            [/-?\d+/, 'number'],
            [/[[\]]/, '@brackets'],
            [/[:?=]/, 'delimiter'],
            [/[ \t\r\n]+/, 'white'],
        ],
    },
};

/** Language configuration: comments, bracket matching, and auto-closing pairs. */
export const DDL_LANGUAGE_CONFIGURATION: monaco.languages.LanguageConfiguration = {
    comments: { lineComment: '#' },
    brackets: [['[', ']']],
    autoClosingPairs: [
        { open: '[', close: ']' },
        { open: '"', close: '"' },
    ],
};
