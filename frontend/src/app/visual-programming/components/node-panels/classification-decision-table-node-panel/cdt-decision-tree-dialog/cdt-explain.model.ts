/**
 * View-side types of the decision tree's Explain feature. The wire contract lives
 * in `core/models/cdt-explain-api.model.ts`.
 */

import { CdtExplainBlockType } from '../../../../core/models/cdt-explain-api.model';
import { CdtTreeBlockKind } from './cdt-decision-tree.model';

/**
 * Which tree blocks map to an explainable step. Exhaustive on purpose: a new kind
 * will not compile until someone decides whether it can be explained.
 */
export const EXPLAIN_BLOCK_BY_KIND: Readonly<Record<CdtTreeBlockKind, CdtExplainBlockType | null>> = {
    'table-entered': null,
    'read-variables': null,
    'rules-region': null,
    'exit-terminator': null,
    'pre-computation': 'pre_computation',
    'post-computation': 'post_computation',
    'row-decision': 'condition',
    'row-prompt': 'prompt',
    'row-manipulation': 'manipulation',
};

/** What the detail window shows. Absent means never asked for. */
export type CdtExplanationState =
    | { readonly status: 'loading' }
    | {
          readonly status: 'ready';
          readonly text: string;
          readonly generatedBy: string;
          /** What it was generated from — see `isOutdated`. */
          readonly fingerprint: string;
      }
    | { readonly status: 'error'; readonly message: string };
