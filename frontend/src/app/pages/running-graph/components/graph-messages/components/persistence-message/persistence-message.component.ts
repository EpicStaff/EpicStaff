import { Component, computed, input, signal } from '@angular/core';
import { AppSvgIconComponent, CopyButtonComponent, JsonViewerComponent } from '@shared/components';
import { PERSISTENCE_MODE_COLORS } from '@shared/models';

import {
    GraphMessage,
    MessageType,
    PersistenceMessageData,
    PersistenceMessageEntry,
    PersistenceMessageMode,
} from '../../../../models/graph-session-message.model';

interface PersistenceChip {
    label: string;
    neutral: boolean;
}

// A table key or a `variables.…` state path; the template colours each kind.
interface MappingPart {
    text: string;
    kind: 'key' | 'path';
}

type JsonTokenType = 'key' | 'string' | 'number' | 'boolean' | 'null' | 'punctuation' | 'plain';

interface JsonToken {
    text: string;
    type: JsonTokenType;
}

// Rendered assignment-style, `target ← source`, matching the data flow:
// read `variables.path ← key`, write `key ← variables.path`, delete just the key.
interface PersistenceRow {
    target: MappingPart;
    source: MappingPart | null;
    value: RowValue | null;
    notFound: boolean;
    tag: 'created' | 'updated' | null;
}

// A scalar or a non-empty object / array goes to the JSON viewer; an empty container (which the
// viewer would draw as an empty box) or a truncated JSON prefix is highlighted inline. `copyText`
// is the full value (pretty JSON, strings raw); null for a truncated prefix, which is not the value.
type RowValue =
    | { kind: 'viewer'; json: unknown; copyText: string }
    | { kind: 'preview'; tokens: JsonToken[]; truncated: boolean; copyText: string | null };

// One JSON token per match: a string (then `:` if it is an object key), number, literal or
// punctuation. A truncated value is the first 200 chars of the JSON text, so a string may end
// without its closing quote (or mid-escape); anything unmatched falls through as plain text.
const JSON_TOKEN =
    /("(?:\\[\s\S]?|[^"\\])*(?:"|$))(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}[\],:]/g;

@Component({
    selector: 'app-persistence-message',
    imports: [AppSvgIconComponent, CopyButtonComponent, JsonViewerComponent],
    templateUrl: './persistence-message.component.html',
    styleUrls: ['./persistence-message.component.scss'],
})
export class PersistenceMessageComponent {
    readonly message = input.required<GraphMessage>();

    protected readonly isExpanded = signal(false);

    protected readonly data = computed<PersistenceMessageData | null>(() => {
        const messageData = this.message().message_data;
        return messageData?.message_type === MessageType.PERSISTENCE ? messageData : null;
    });

    protected readonly accent = computed(() => {
        const data = this.data();
        // The left stripe takes the mode colour of the canvas node; everything else keeps --color-persistence.
        return data ? PERSISTENCE_MODE_COLORS[data.mode] : null;
    });

    // The title text before the table name, which the template renders in the accent colour.
    protected readonly titlePrefix = computed(() => {
        const data = this.data();
        if (!data) return '';
        switch (data.mode) {
            case 'read':
                return `Read ${countKeys(data.entries.length)} from table`;
            case 'write':
                return `Wrote ${countKeys(data.entries.length)} to table`;
            case 'delete': {
                const removed = data.deleted_count ?? 0;
                return removed === 0 ? 'No keys removed from table' : `Removed ${countKeys(removed)} from table`;
            }
        }
    });

    protected readonly chips = computed<PersistenceChip[]>(() => {
        const data = this.data();
        if (!data) return [];
        const total = data.entries.length;
        switch (data.mode) {
            case 'read': {
                const found = data.entries.filter((entry) => entry.found === true).length;
                return withSecondary({ label: `${found} found`, neutral: false }, total - found, 'not found');
            }
            case 'write': {
                const created = data.entries.filter((entry) => entry.created === true).length;
                return withSecondary({ label: `${created} created`, neutral: false }, total - created, 'updated');
            }
            case 'delete':
                return [{ label: `${data.deleted_count ?? 0} of ${total}`, neutral: true }];
        }
    });

    protected readonly missingNote = computed(() => {
        const data = this.data();
        if (data?.mode !== 'delete') return null;
        const missing = data.entries.length - (data.deleted_count ?? 0);
        if (missing <= 0) return null;
        return `${countKeys(missing)} ${missing === 1 ? 'was' : 'were'} not in the table`;
    });

    protected readonly rows = computed<PersistenceRow[]>(() => {
        const data = this.data();
        if (!data) return [];
        return data.entries.map((entry) => {
            const notFound = data.mode === 'read' && entry.found === false;
            return {
                ...toAssignment(data.mode, entry),
                value: data.mode === 'delete' || notFound ? null : toRowValue(entry),
                notFound,
                tag: data.mode === 'write' ? (entry.created ? 'created' : 'updated') : null,
            };
        });
    });

    protected toggle(): void {
        this.isExpanded.update((expanded) => !expanded);
    }
}

function toAssignment(
    mode: PersistenceMessageMode,
    entry: PersistenceMessageEntry
): Pick<PersistenceRow, 'target' | 'source'> {
    const key: MappingPart = { text: entry.key, kind: 'key' };
    const path: MappingPart | null = entry.path ? { text: entry.path, kind: 'path' } : null;
    switch (mode) {
        case 'read':
            return path ? { target: path, source: key } : { target: key, source: null };
        case 'write':
            return { target: key, source: path };
        case 'delete':
            return { target: key, source: null };
    }
}

function toRowValue({ value, truncated }: PersistenceMessageEntry): RowValue {
    if (truncated) {
        const tokens: JsonToken[] = [...tokenizeJson(String(value)), { text: '…', type: 'plain' }];
        return { kind: 'preview', tokens, truncated, copyText: null };
    }
    const json = value ?? null;
    const copyText = typeof json === 'string' ? json : JSON.stringify(json, null, 2);
    if (typeof json === 'object' && json !== null && Object.keys(json).length === 0) {
        return { kind: 'preview', tokens: tokenizeJson(JSON.stringify(json)), truncated, copyText };
    }
    return { kind: 'viewer', json, copyText };
}

function tokenizeJson(text: string): JsonToken[] {
    const tokens: JsonToken[] = [];
    let plainStart = 0;
    for (const match of text.matchAll(JSON_TOKEN)) {
        if (match.index > plainStart) tokens.push({ text: text.slice(plainStart, match.index), type: 'plain' });
        const [token, string, colon] = match;
        if (string !== undefined) {
            tokens.push({ text: string, type: colon ? 'key' : 'string' });
            if (colon) tokens.push({ text: colon, type: 'punctuation' });
        } else {
            tokens.push({ text: token, type: literalType(token) });
        }
        plainStart = match.index + token.length;
    }
    if (plainStart < text.length) tokens.push({ text: text.slice(plainStart), type: 'plain' });
    return tokens;
}

function literalType(token: string): JsonTokenType {
    if (token === 'null') return 'null';
    if (token === 'true' || token === 'false') return 'boolean';
    return /^-?\d/.test(token) ? 'number' : 'punctuation';
}

function countKeys(count: number): string {
    return `${count} ${count === 1 ? 'key' : 'keys'}`;
}

function withSecondary(primary: PersistenceChip, secondaryCount: number, secondaryLabel: string): PersistenceChip[] {
    return secondaryCount > 0 ? [primary, { label: `${secondaryCount} ${secondaryLabel}`, neutral: true }] : [primary];
}
