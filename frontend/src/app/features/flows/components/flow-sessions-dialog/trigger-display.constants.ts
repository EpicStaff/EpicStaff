import { TriggerType } from '../../services/flows-sessions.service';

export interface TriggerDisplay {
    label: string;
    icon: string | null;
    color: string | null;
}

export const TRIGGER_DISPLAY: Record<TriggerType, TriggerDisplay> = {
    manual: { label: 'Manual Run', icon: 'ti ti-player-play', color: null },
    webhook: { label: 'Webhook', icon: 'ti ti-world', color: '#21f367' },
    telegram: { label: 'Telegram', icon: 'ti ti-brand-telegram', color: '#229ED9' },
    schedule: { label: 'Schedule', icon: 'ti ti-calendar', color: '#FF5C00' },
    parent_flow: { label: 'Another flow', icon: 'ti ti-hierarchy-2', color: '#00bfa5' },
};

export const UNKNOWN_TRIGGER_DISPLAY: TriggerDisplay = { label: 'Other', icon: null, color: null };

export function getTriggerDisplay(triggerType: string): TriggerDisplay {
    const known = (TRIGGER_DISPLAY as Record<string, TriggerDisplay>)[triggerType];
    return known ?? { ...UNKNOWN_TRIGGER_DISPLAY, label: triggerType };
}
