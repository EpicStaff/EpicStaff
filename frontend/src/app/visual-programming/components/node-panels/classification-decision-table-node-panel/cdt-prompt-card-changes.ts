import { KeyedItemChange, keyedItemChanges, UnionNodeDiffState } from '../../../utils/diff';
import { DiffFieldMarkChange } from '../../diff-field-mark/diff-field-mark.component';

/** How a prompt card (a version prompt) shows what a restore does to it: marked when changed, framed green when added. */
export interface CdtPromptCardMark {
    added: boolean;
    /** The card's changed fields on the canvas and in the version; `null` for a card a restore does not change. */
    change: DiffFieldMarkChange | null;
    /** The card's tooltip and description instead of the values: the fields a restore changes. */
    hint: string | null;
}

/** A card a restore keeps as it is. */
export const KEPT_PROMPT_CARD: CdtPromptCardMark = { added: false, change: null, hint: null };

/** A canvas prompt the version does not have (a restore removes it), as its card shows it. */
export interface RemovedCdtPrompt {
    id: string;
    resultVariable: string;
}

/** What a restore does to the prompt cards of a Classification Decision Table. */
export interface CdtPromptCardChanges {
    /** By prompt id; a prompt without an entry is kept. */
    cards: ReadonlyMap<string, CdtPromptCardMark>;
    /** The canvas prompts a restore removes. */
    removed: RemovedCdtPrompt[];
}

/** The prompt fields the diff compares, by the words the card's tooltip uses, in the card's order. */
const LABEL_BY_FIELD: Readonly<Record<string, string>> = {
    llm_config: 'LLM',
    result_variable: 'Result variable',
    prompt_text: 'Prompt text',
    output_schema: 'Output schema',
    // No field of its own in the card: the card's mark is its only one.
    variable_mappings: 'Variable mappings',
};

/**
 * What a restore does to each prompt card (Changes tab of a version preview); prompts are paired by their id. `null`
 * when the node shows no field marks or no prompt changed.
 */
export function cdtPromptCardChanges(diff: UnionNodeDiffState | null): CdtPromptCardChanges | null {
    const items = keyedItemChanges(diff, 'prompts');
    if (items === null) return null;
    const cards = new Map<string, CdtPromptCardMark>();
    for (const item of items) {
        if (item.status === 'added') cards.set(item.key, { ...KEPT_PROMPT_CARD, added: true });
        if (item.status === 'changed') {
            cards.set(item.key, {
                added: false,
                change: item,
                hint: `Changed fields: ${changedFields(item).join(', ')}.`,
            });
        }
    }
    const removed = items.filter((item) => item.status === 'deleted').map(removedPrompt);
    return { cards, removed };
}

/** A prompt whose value is not an object changes as a whole: every field. */
function changedFields(item: KeyedItemChange): string[] {
    const fields = item.fields.length > 0 ? item.fields : Object.keys(LABEL_BY_FIELD);
    return Object.entries(LABEL_BY_FIELD)
        .filter(([field]) => fields.includes(field))
        .map(([, label]) => label);
}

function removedPrompt(item: KeyedItemChange): RemovedCdtPrompt {
    const prompt = (item.current ?? {}) as Partial<Record<string, unknown>>;
    const resultVariable = prompt['result_variable'];
    return { id: item.key, resultVariable: typeof resultVariable === 'string' ? resultVariable : '' };
}
