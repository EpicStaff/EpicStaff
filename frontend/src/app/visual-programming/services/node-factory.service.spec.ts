import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel } from '../core/models/node.model';
import { NodeFactoryService } from './node-factory.service';
import { SandboxLimitsStorageService } from './sandbox-limits-storage.service';

describe('NodeFactoryService execution timeout of a new node', () => {
    function createUnder(maxMinutes: number, type: NodeType, overrides?: Partial<NodeModel>): NodeModel {
        TestBed.inject(SandboxLimitsStorageService).setLimits({ max_execution_timeout_minutes: maxMinutes });
        return TestBed.inject(NodeFactoryService).createNode(type, overrides);
    }

    function timeoutOf(node: NodeModel): unknown {
        return (node as { execution_timeout?: unknown }).execution_timeout;
    }

    it.each([NodeType.PYTHON, NodeType.WEBHOOK_TRIGGER, NodeType.CLASSIFICATION_TABLE])(
        'starts a %s node, whose code the user writes, at 3 minutes',
        (type) => {
            expect(timeoutOf(createUnder(60, type))).toBe(3);
        }
    );

    it.each([NodeType.FILE_EXTRACTOR, NodeType.AUDIO_TO_TEXT])(
        'starts a %s node, whose run time grows with the file, at the ceiling',
        (type) => {
            expect(timeoutOf(createUnder(60, type))).toBe(60);
        }
    );

    it.each([NodeType.PYTHON, NodeType.WEBHOOK_TRIGGER, NodeType.CLASSIFICATION_TABLE])(
        'starts a %s node at a ceiling below 3 minutes, never above it',
        (type) => {
            expect(timeoutOf(createUnder(2, type))).toBe(2);
        }
    );

    it('gives a node that runs no sandbox code no timeout', () => {
        expect(createUnder(60, NodeType.AGENT)).not.toHaveProperty('execution_timeout');
        expect(createUnder(60, NodeType.TABLE)).not.toHaveProperty('execution_timeout');
    });

    it('keeps the timeout of a pasted or duplicated node', () => {
        const pasted = createUnder(60, NodeType.PYTHON, { execution_timeout: 17 } as Partial<NodeModel>);

        expect(timeoutOf(pasted)).toBe(17);
    });
});
