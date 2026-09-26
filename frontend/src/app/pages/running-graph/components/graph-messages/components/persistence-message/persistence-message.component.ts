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

// Rendered assignment-style, `target ← source`, matching the data flow:
// read `variables.path ← key`, write `key ← variables.path`, delete just the key.
interface PersistenceRow {
    target: string;
    source: string | null;
    preview: string | null;
    notFound: boolean;
    tag: 'created' | 'updated' | null;
}

const MODE_ICONS: Record<PersistenceMessageMode, string> = {
    read: 'download',
    write: 'upload',
    delete: 'trash',
};

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

    protected readonly icon = computed(() => {
        const data = this.data();
        return data ? MODE_ICONS[data.mode] : '';
    });

    // The title text before the table name, which the template renders in the accent colour.
    protected readonly titlePrefix = computed(() => {
        const data = this.data();
        if (!data) return '';
        switch (data.mode) {
            case 'read':
                return `Read ${countKeys(data.entries.length)} from`;
            case 'write':
                return `Wrote ${countKeys(data.entries.length)} to`;
            case 'delete': {
                const removed = data.deleted_count ?? 0;
                return removed === 0 ? 'No keys removed from' : `Removed ${countKeys(removed)} from`;
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
            preview: entry.value_preview === null ? null : `${entry.value_preview}${entry.truncated ? '…' : ''}`,
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
    switch (mode) {
        case 'read':
            return entry.path ? { target: entry.path, source: entry.key } : { target: entry.key, source: null };
        case 'write':
            return { target: entry.key, source: entry.path };
        case 'delete':
            return { target: entry.key, source: null };
    }
}

function countKeys(count: number): string {
    return `${count} ${count === 1 ? 'key' : 'keys'}`;
}

function withSecondary(primary: PersistenceChip, secondaryCount: number, secondaryLabel: string): PersistenceChip[] {
    return secondaryCount > 0 ? [primary, { label: `${secondaryCount} ${secondaryLabel}`, neutral: true }] : [primary];
}
