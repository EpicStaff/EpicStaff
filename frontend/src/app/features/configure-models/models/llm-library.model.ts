import { Signal } from '@angular/core';
import { BulkDeleteLabel, BulkDeleteTarget, LlmLibraryModel } from '@shared/models';
import { Observable } from 'rxjs';

import { RealtimeConfig, RealtimeProvider } from '../components/realtime-config-form/realtime-config-form.component';
import { LlmLibrarySelectionKind } from '../utils/llm-library-bulk-delete.util';
import { ProviderCreationOrder } from '../utils/llm-library-layout.util';

/** A realtime (voice) provider of the LLM Library: its storage, and how its heading and deletes name it. */
export interface VoiceProvider {
    key: RealtimeProvider;
    /** The provider's name, as its group heading shows it. */
    name: string;
    deleteLabel: BulkDeleteLabel;
    storage: {
        configs: Signal<RealtimeConfig[]>;
        getAllConfigs(force?: boolean): Observable<unknown[]>;
    } & BulkDeleteTarget;
}

/** What the LLM Library loads on its own, and so can fail to load and retry on its own. */
export type LibraryLoadKey = 'llm' | 'embedding' | 'realtime' | 'transcription' | 'system_one' | RealtimeProvider;

/** The collapsible sections of the page, in their order. */
export const LIBRARY_SECTION_KEYS = ['llm', 'embedding', 'voice', 'system_one'] as const;
export type LibrarySectionKey = (typeof LIBRARY_SECTION_KEYS)[number];

export function isLibrarySectionKey(value: unknown): value is LibrarySectionKey {
    return (LIBRARY_SECTION_KEYS as readonly unknown[]).includes(value);
}

/** A card on the page: what selects it and what its buttons do. */
export interface LibraryCard {
    selectionKey: string;
    kind: LlmLibrarySelectionKind;
    id: number;
    model: LlmLibraryModel;
    edit(): void;
    remove(): void;
    viewDetails(trigger: HTMLElement): void;
}

/** A provider's cards under its heading; System One has one group with no heading (`name` null). */
export interface LibraryProviderGroup {
    id: string;
    name: string | null;
    icon: string;
    /** The icon is a multi-colour logo, painted in the text colour by a filter. */
    isTinted: boolean;
    order: ProviderCreationOrder;
    cards: LibraryCard[];
}

export interface LibrarySectionError {
    key: LibraryLoadKey;
    title: string;
}

export interface LibrarySection {
    key: LibrarySectionKey;
    title: string;
    errors: LibrarySectionError[];
    /** Provider groups packed into rows (see `packLlmLibraryRows`). */
    rows: LibraryProviderGroup[][];
    /** The providers, comma-separated, as a collapsed heading lists them; empty for System One. */
    providerList: string;
    /** Every card shown in the section, by selection key. */
    selectionKeys: string[];
}
