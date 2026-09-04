import { signal, WritableSignal } from '@angular/core';

import { InlineSurface } from '../../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { hasSuggestedRagParams } from '../../../../utils/surface/inline-surface.mapper';

export class LlmChangedWarningState {
    readonly active: WritableSignal<boolean> = signal(false);

    checkAgentChange(
        previousLlmConfigId: number | null,
        nextLlmConfigId: number | null,
        inlineSurface: InlineSurface | null
    ): void {
        if (nextLlmConfigId !== previousLlmConfigId && hasSuggestedRagParams(inlineSurface)) {
            this.active.set(true);
        }
    }

    clear(): void {
        this.active.set(false);
    }
}
