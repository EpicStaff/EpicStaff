import { Signal } from '@angular/core';
import { WebhookTriggerSelectComponent } from '@shared/components';

import { linkedEntityFormat } from '../../../../utils/diff';

/**
 * How the field mark of a webhook trigger field names a trigger: as the trigger select lists it, from the triggers
 * that select already loaded; a trigger it does not list as `trigger #id`.
 */
export function webhookTriggerNameFormat(
    select: Signal<WebhookTriggerSelectComponent | undefined>
): (value: unknown) => string {
    return linkedEntityFormat('trigger', (id) => {
        const triggerSelect = select();
        const trigger = triggerSelect?.triggers().find((candidate) => candidate.id === id);
        return triggerSelect && trigger ? triggerSelect.displayLabel(trigger) : null;
    });
}
