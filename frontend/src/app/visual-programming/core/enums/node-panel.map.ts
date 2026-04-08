import { Type } from '@angular/core';

import { AudioToTextNodePanelComponent } from '../../components/node-panels/audio-to-text-node-panel/audio-to-text-node-panel.component';
import { CodeAgentNodePanelComponent } from '../../components/node-panels/code-agent-node-panel/code-agent-node-panel.component';
import { ConditionalEdgeNodePanelComponent } from '../../components/node-panels/conditional-edge-node-panel/conditional-edge-node-panel.component';
import { DecisionTableNodePanelComponent } from '../../components/node-panels/decision-table-node-panel/decision-table-node-panel.component';
import { EndNodePanelComponent } from '../../components/node-panels/end-node-panel/end-node-panel.component';
import { FileExtractorNodePanelComponent } from '../../components/node-panels/file-extractor-node-panel/file-extractor-node-panel.component';
import { ProjectNodePanelComponent } from '../../components/node-panels/project-node-panel/project-node-panel.component';
import { PythonNodePanelComponent } from '../../components/node-panels/python-node-panel/python-node-panel.component';
import { SubGraphNodePanelComponent } from '../../components/node-panels/subgraph-node-panel/subgraph-node-panel.component';
import { TelegramTriggerNodePanelComponent } from '../../components/node-panels/telegram-trigger-node-panel/telegram-trigger-node-panel.component';
import { WebhookTriggerNodePanelComponent } from '../../components/node-panels/webhook-trigger-node-panel/webhook-trigger-node-panel.component';
import { NodeModel } from '../models/node.model';
import { NodePanel } from '../models/node-panel.interface';
import { NodeType } from './node-type';

const asNodePanelComponent = <T extends NodeModel>(component: Type<NodePanel<T>>): Type<NodePanel<NodeModel>> =>
    component as unknown as Type<NodePanel<NodeModel>>;

export const PANEL_COMPONENT_MAP: Record<string, Type<NodePanel<NodeModel>>> = {
    python: asNodePanelComponent(PythonNodePanelComponent),
    project: asNodePanelComponent(ProjectNodePanelComponent),
    edge: asNodePanelComponent(ConditionalEdgeNodePanelComponent),
    'file-extractor': asNodePanelComponent(FileExtractorNodePanelComponent),
    'webhook-trigger': asNodePanelComponent(WebhookTriggerNodePanelComponent),
    'telegram-trigger': asNodePanelComponent(TelegramTriggerNodePanelComponent),
    end: asNodePanelComponent(EndNodePanelComponent),
    subgraph: asNodePanelComponent(SubGraphNodePanelComponent),
    table: asNodePanelComponent(DecisionTableNodePanelComponent),
    [NodeType.AUDIO_TO_TEXT]: asNodePanelComponent(AudioToTextNodePanelComponent),
    [NodeType.CODE_AGENT]: asNodePanelComponent(CodeAgentNodePanelComponent),
    // start: StartNodePanelComponent,
};
