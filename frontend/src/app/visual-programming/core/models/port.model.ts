export interface BasePort {
    port_type: 'input' | 'output' | 'input-output';
    role: string;
    multiple: boolean;
    label: string;
    allowedConnections: string[];
    position: 'left' | 'right' | 'top' | 'bottom';
    color?: string;
}
export interface ViewPort extends BasePort {
    id: CustomPortId;
}

//nodeid_port-role
export type CustomPortId = `${string}_${string}`;
