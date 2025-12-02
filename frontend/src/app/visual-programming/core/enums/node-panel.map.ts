import { Type } from '@angular/core';
import { NodePanel } from '../models/node-panel.interface';
import { ProjectNodePanelComponent } from '../../components/node-panels/project-node-panel/project-node-panel.component';
import { PythonNodePanelComponent } from '../../components/node-panels/python-node-panel/python-node-panel.component';
import { ConditionalEdgeNodePanelComponent } from '../../components/node-panels/conditional-edge-node-panel/conditional-edge-node-panel.component';
import { EndNodePanelComponent } from '../../components/node-panels/end-node-panel/end-node-panel.component';
import { FileExtractorNodePanelComponent } from '../../components/node-panels/file-extractor-node-panel/file-extractor-node-panel.component';
import { SubGraphNodePanelComponent } from '../../components/node-panels/subgraph-node-panel/subgraph-node-panel.component';
import { DecisionTableNodePanelComponent } from '../../components/node-panels/decision-table-node-panel/decision-table-node-panel.component';
import { WebhookTriggerNodePanelComponent } from '../../components/node-panels/webhook-trigger-node-panel/webhook-trigger-node-panel';

export const PANEL_COMPONENT_MAP: Record<string, Type<NodePanel<any>>> = {
    python: PythonNodePanelComponent,
    project: ProjectNodePanelComponent,
    edge: ConditionalEdgeNodePanelComponent,
    'file-extractor': FileExtractorNodePanelComponent,
    'webhook-trigger': WebhookTriggerNodePanelComponent,
    end: EndNodePanelComponent,
    subgraph: SubGraphNodePanelComponent,
    table: DecisionTableNodePanelComponent,
};
