import { TELEGRAM_TRIGGER_FIELDS } from '../../core/constants/telegram-trigger-fields';
import { TelegramFieldParent, TelegramTriggerFieldWithModel } from '../../core/models/telegram-trigger.model';
import { TestPayloadRuleMessages } from './check-test-payload-text';
import { isPlainJsonObject, TriggerTestPayload } from './validate-test-payload';

/** A field picked on a Telegram trigger node: `telegram_payload[parent][field_name]` at runtime. */
export interface TelegramPickedField {
    parent: string;
    field_name: string;
}

export type TelegramFieldCatalog = Record<TelegramFieldParent, TelegramTriggerFieldWithModel[]>;

export const TELEGRAM_NO_FIELDS_SELECTED_MESSAGE =
    'This Telegram trigger has no fields selected; select fields before running a test.';

/**
 * Top-level keys of the Telegram update envelope (a real update always carries `update_id`).
 * They are allowed next to the picked parents and ignored: their values are never inspected.
 */
export const TELEGRAM_UPDATE_ENVELOPE_KEYS: ReadonlySet<string> = new Set(['update_id']);

/**
 * Mirrors the backend `TelegramTriggerTestRunStrategy.validate_payload` (the backend stays the
 * authority). Key-level only: the payload may use only the picked parents (plus the ignored
 * envelope keys) and, under each parent, only the picked fields. `{}`, empty parents and omitted
 * fields are allowed; values are never inspected.
 * A node with no picked fields is reported alone, as a hint: nothing is wrong with the payload yet.
 */
export function validateTelegramTestPayload(
    payload: TriggerTestPayload,
    pickedFields: readonly TelegramPickedField[]
): TestPayloadRuleMessages {
    const pickedFieldNamesByParent = new Map<string, Set<string>>();
    for (const field of pickedFields) {
        const fieldNames = pickedFieldNamesByParent.get(field.parent) ?? new Set<string>();
        fieldNames.add(field.field_name);
        pickedFieldNamesByParent.set(field.parent, fieldNames);
    }

    if (pickedFieldNamesByParent.size === 0) {
        return { errors: [], hints: [TELEGRAM_NO_FIELDS_SELECTED_MESSAGE] };
    }

    const errors: string[] = [];
    for (const [parent, parentValue] of Object.entries(payload)) {
        if (TELEGRAM_UPDATE_ENVELOPE_KEYS.has(parent)) {
            continue;
        }
        const pickedFieldNames = pickedFieldNamesByParent.get(parent);
        if (!pickedFieldNames) {
            errors.push(`'${parent}': not a field parent selected on this node`);
            continue;
        }
        if (!isPlainJsonObject(parentValue)) {
            errors.push(`'${parent}' must be an object`);
            continue;
        }
        for (const fieldName of Object.keys(parentValue)) {
            if (!pickedFieldNames.has(fieldName)) {
                errors.push(`'${parent}.${fieldName}': field not selected on this node`);
            }
        }
    }
    return { errors, hints: [] };
}

/**
 * A sample Telegram update holding every picked field, shaped like the real runtime payload:
 * `{[parent]: {[field_name]: example value}}`, with the example values from the field catalog.
 * The envelope keys (`update_id`) are left out: they are allowed but never read by the node.
 */
export function buildTelegramSamplePayload(
    pickedFields: readonly TelegramPickedField[],
    catalog: TelegramFieldCatalog = TELEGRAM_TRIGGER_FIELDS
): TriggerTestPayload {
    const sample: Record<string, Record<string, unknown>> = {};
    for (const field of pickedFields) {
        const catalogField = catalog[field.parent as TelegramFieldParent]?.find(
            (candidate) => candidate.field_name === field.field_name
        );
        sample[field.parent] ??= {};
        sample[field.parent][field.field_name] = catalogField?.model ?? null;
    }
    return sample;
}
