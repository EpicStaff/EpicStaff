import { IPoint } from '@foblex/2d';

/** Canvas pan and zoom, as captured from and restored to the flow canvas. */
export interface FlowViewport {
    position: IPoint;
    scale: number;
}
