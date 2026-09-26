import { Component, computed, input, signal } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

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
    preview: JsonToken[] | null;
    notFound: boolean;
    tag: 'created' | 'updated' | null;
}

interface ModeIcon {
    name: string;
    size: string;
}

// download / upload-outline are 24-box outlines with ~3px of padding; trash fills its 13x16 box
// edge to edge, so it is drawn smaller to match their visible height.
const MODE_ICONS: Record<PersistenceMessageMode, ModeIcon> = {
    read: { name: 'download', size: '1.25rem' },
    write: { name: 'upload-outline', size: '1.25rem' },
    delete: { name: 'trash', size: '0.9rem' },
};

// One JSON token per match: a string (then `:` if it is an object key), number, literal or
// punctuation. Previews are cut at 200 chars, so a string may end without its closing quote
// (or mid-escape); anything unmatched falls through as plain text.
const JSON_TOKEN =
    /("(?:\\[\s\S]?|[^"\\])*(?:"|$))(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}[\],:]/g;

@Component({
    selector: 'app-persistence-message',
    imports: [AppSvgIconComponent],
    templateUrl: './persistence-message.component.html',
    styleUrls: ['./persistence-message.component.scss'],
})
export class PersistenceMessageComponent {
    readonly message = input.required<GraphMessage>();

    protected readonly isExpanded = signal(false);
    protected readonly isKeysExpanded = signal(true);

    protected readonly data = computed<PersistenceMessageData | null>(() => {
        const messageData = this.message().message_data;
        return messageData?.message_type === MessageType.PERSISTENCE ? messageData : null;
    });

    protected readonly icon = computed<ModeIcon | null>(() => {
        const data = this.data();
        return data ? MODE_ICONS[data.mode] : null;
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
        return data.entries.map((entry) => ({
            ...toAssignment(data.mode, entry),
            preview: entry.value_preview === null ? null : previewTokens(entry.value_preview, entry.truncated),
            notFound: data.mode === 'read' && entry.found === false,
            tag: data.mode === 'write' ? (entry.created ? 'created' : 'updated') : null,
        }));
    });

    protected toggle(): void {
        this.isExpanded.update((expanded) => !expanded);
    }

    protected toggleKeys(): void {
        this.isKeysExpanded.update((expanded) => !expanded);
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

function previewTokens(preview: string, truncated: boolean): JsonToken[] {
    const tokens = tokenizeJson(preview);
    return truncated ? [...tokens, { text: '…', type: 'plain' }] : tokens;
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
