import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormGroup } from '@angular/forms';

import { KnowledgeRetrieverNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';

@Component({
    selector: 'app-knowledge-retriever-node-panel',
    templateUrl: './knowledge-retriever-node-panel.component.html',
    styleUrls: ['./knowledge-retriever-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KnowledgeRetrieverNodePanelComponent extends BaseSidePanel<KnowledgeRetrieverNodeModel> {
    initializeForm(): FormGroup {
        return this.fb.group({});
    }

    createUpdatedNode(): KnowledgeRetrieverNodeModel {
        return {} as KnowledgeRetrieverNodeModel;
    }
}
