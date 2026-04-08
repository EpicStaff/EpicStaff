import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

import { NodeModel } from '../../../../core/models/node.model';
@Component({
    selector: 'app-node-preview',
    standalone: true,
    imports: [CommonModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    template: `
        <div class="node-preview-container">
            <div class="interactive-node-body">
                <div class="header">
                    <div class="icon-wrapper">
                        <i [class]="getNodeIcon()"></i>
                    </div>
                    <div class="title">
                        {{ node.node_name }}
                    </div>
                </div>
            </div>

            <!-- Ports indicators -->
            <div class="port-left" *ngIf="hasInputPorts()"></div>
            <div class="port-right" *ngIf="hasOutputPorts()"></div>
        </div>
    `,
    styles: [
        `
            /* Preview Node Styling - Neutral dark gray colors */
            .node-preview-container {
                position: relative;
                width: 330px;
                height: 60px;
                background-color: #1e1e1e;
                border-radius: 6px;
                border: 1px solid #333;
                padding: 10px 15px;
                display: flex;
                align-items: center;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);

                /* Main node body */
                .interactive-node-body {
                    display: flex;
                    width: 100%;
                    height: 100%;

                    .header {
                        display: flex;
                        align-items: center;
                        gap: 12px;
                        width: 100%;

                        .icon-wrapper {
                            display: flex;
                            align-items: center;
                            justify-content: center;

                            i {
                                color: #666666; /* Neutral gray color */
                                font-size: 22px;
                            }
                        }

                        .title {
                            font-size: 16px;
                            font-weight: 500;
                            color: #cccccc; /* Light gray text */
                            overflow: hidden;
                            text-overflow: ellipsis;
                            white-space: nowrap;
                        }
                    }
                }

                /* Port styles with neutral colors */
                .port-left,
                .port-right {
                    position: absolute;
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    top: 50%;
                    transform: translateY(-50%);
                }

                .port-left {
                    left: -5px;
                    background-color: #4d4d4d; /* Dark gray for input port */
                }

                .port-right {
                    right: -5px;
                    border: 1px solid #4d4d4d; /* Dark gray outline for output port */
                    background-color: #1e1e1e;
                }
            }
        `,
    ],
})
export class NodePreviewComponent {
    @Input() node!: NodeModel;

    public getNodeIcon(): string {
        if (!this.node) {
            return 'ti ti-code';
        }
        return this.node.icon || 'ti ti-code';
    }

    public hasInputPorts(): boolean {
        return (
            this.node.ports?.some((port) => port.port_type === 'input' || port.port_type === 'input-output') ?? false
        );
    }

    public hasOutputPorts(): boolean {
        return (
            this.node.ports?.some((port) => port.port_type === 'output' || port.port_type === 'input-output') ?? false
        );
    }
}
