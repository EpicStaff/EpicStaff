import {
    CDT_COLUMN_KIND,
    CDT_EXPR_PARAMS_GROUP_ID,
    CDT_FREEZE_COPY,
    CDT_MANIP_PARAMS_GROUP_ID,
} from '../../cdt.constants';

export type CdtFreezeSide = 'left' | 'right';

/** Only one side is frozen at a time: every column from the anchor to that side's edge is pinned. */
export interface CdtFreezeState {
    side: CdtFreezeSide;
    /** A column id, or a Params group id: a group freezes as a whole, whatever children it has now. */
    anchorColId: string;
}

export interface CdtFreezeMenuItem {
    side: CdtFreezeSide;
    label: string;
    /** Set when the other side is frozen; shown as the item's tooltip. */
    disabledReason: string | null;
}

const SIDE_LABEL: Record<CdtFreezeSide, string> = { left: 'Left', right: 'Right' };
const BOTH_SIDES: readonly CdtFreezeSide[] = ['left', 'right'];

/** The sides each column (or Params group) may be frozen from, from the design. Not listed: no freeze. */
export const CDT_FREEZE_SIDES_BY_ANCHOR: Readonly<Record<string, readonly CdtFreezeSide[]>> = {
    group_name: ['left'],
    [CDT_COLUMN_KIND.EXPRESSION]: BOTH_SIDES,
    [CDT_EXPR_PARAMS_GROUP_ID]: BOTH_SIDES,
    prompt_id: BOTH_SIDES,
    [CDT_COLUMN_KIND.MANIPULATION]: BOTH_SIDES,
    [CDT_MANIP_PARAMS_GROUP_ID]: BOTH_SIDES,
    route_code: BOTH_SIDES,
    continue_flag: ['right'],
};

/**
 * The freeze items of the header menu of `anchorId` (a column id or a Params group id): one per
 * side it may be frozen from.
 */
export function buildFreezeMenuItems(
    freeze: CdtFreezeState | null,
    anchorId: string,
    isTooWide: (side: CdtFreezeSide) => boolean
): CdtFreezeMenuItem[] {
    const isAnchor = freeze?.anchorColId === anchorId;
    return (CDT_FREEZE_SIDES_BY_ANCHOR[anchorId] ?? []).map((side) => {
        if (freeze && freeze.side !== side) {
            return {
                side,
                label: `Freeze All ${SIDE_LABEL[side]}`,
                disabledReason: `Unfreeze ${SIDE_LABEL[freeze.side]} first`,
            };
        }
        if (isAnchor) {
            return { side, label: `Unfreeze ${SIDE_LABEL[side]}`, disabledReason: null };
        }
        return {
            side,
            label: `Freeze All ${SIDE_LABEL[side]}`,
            disabledReason: isTooWide(side) ? CDT_FREEZE_COPY.tooWide : null,
        };
    });
}
