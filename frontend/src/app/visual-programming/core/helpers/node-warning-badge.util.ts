import { MatTooltip } from '@angular/material/tooltip';

/**
 * One warning a node raises on the canvas. `blocked` is the red "missing reference" style, `warning` the red
 * alert-triangle one.
 */
export interface NodeWarningBadge {
    kind: 'warning' | 'blocked';
    label: string;
    tooltip: string;
}

/** What a header shows in place of two or more badges: one chip counting them, with every message on its own bulleted line. */
export interface NodeWarningChip {
    label: string;
    tooltip: string;
    tooltipClass: string;
}

/** Tooltip class that keeps the line breaks of a chip's message. */
const NODE_WARNING_CHIP_TOOLTIP_CLASS = 'multiline-tooltip';

/** The chip for two or more messages. A single message is shown as its own badge instead. */
export function buildNodeWarningChip(messages: readonly string[]): NodeWarningChip {
    return {
        label: `${messages.length} issues`,
        tooltip: messages.map((message) => `• ${message}`).join('\n'),
        tooltipClass: NODE_WARNING_CHIP_TOOLTIP_CLASS,
    };
}

/** Lets a node name's tooltip show only when the name is cut off, so a name that fits is not announced twice. */
export function enableTooltipOnlyWhenTruncated(tooltip: MatTooltip, nameElement: HTMLElement): void {
    tooltip.disabled = nameElement.scrollWidth <= nameElement.clientWidth;
}
