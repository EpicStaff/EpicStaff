import { BoardNodeSnapshot, PixelRect } from './pixel-explosion';

const NODE_SELECTOR = '.f-node';
/** Attribute foblex renders from `[fNodeId]` on every node host. */
const NODE_ID_ATTRIBUTE = 'data-f-node-id';
/** The node-type icon, whose colour is bound to `node.color` in the base-node template. */
const NODE_ICON_SELECTOR = '.icon-wrapper i';

/** Reads the on-screen rect of every node visible inside `boardElement` and resolves its node-type colour. */
export function captureBoardNodes(
    boardElement: HTMLElement,
    colorsByNodeId: ReadonlyMap<string, string>,
    fallbackColor: string
): BoardNodeSnapshot[] {
    const boardRect = boardElement.getBoundingClientRect();
    return Array.from(boardElement.querySelectorAll<HTMLElement>(NODE_SELECTOR))
        .map((nodeElement) => captureNode(nodeElement, boardRect, colorsByNodeId, fallbackColor))
        .filter((snapshot): snapshot is BoardNodeSnapshot => snapshot !== null);
}

function captureNode(
    nodeElement: HTMLElement,
    boardRect: DOMRect,
    colorsByNodeId: ReadonlyMap<string, string>,
    fallbackColor: string
): BoardNodeSnapshot | null {
    const nodeRect = nodeElement.getBoundingClientRect();
    if (nodeRect.width < 1 || nodeRect.height < 1 || !intersects(nodeRect, boardRect)) return null;

    return {
        rect: toLocalRect(nodeRect, boardRect),
        cornerRadius: readCornerRadius(nodeElement) * zoomScale(nodeElement, nodeRect),
        color: resolveNodeColor(nodeElement, colorsByNodeId) ?? fallbackColor,
    };
}

/** Prefers the model colour by node id, then the computed colour of the node-type icon. */
function resolveNodeColor(nodeElement: HTMLElement, colorsByNodeId: ReadonlyMap<string, string>): string | null {
    const nodeId = nodeElement.getAttribute(NODE_ID_ATTRIBUTE);
    const modelColor = nodeId ? colorsByNodeId.get(nodeId) : undefined;
    if (modelColor) return modelColor;

    const icon = nodeElement.querySelector(NODE_ICON_SELECTOR);
    const iconColor = icon ? getComputedStyle(icon).color : '';
    return iconColor || null;
}

/** Uses the host radius, or the first child's when the host itself is square (the body carries the rounding). */
function readCornerRadius(nodeElement: HTMLElement): number {
    const hostRadius = parsePixelLength(getComputedStyle(nodeElement).borderTopLeftRadius);
    if (hostRadius > 0 || !nodeElement.firstElementChild) return hostRadius;
    return parsePixelLength(getComputedStyle(nodeElement.firstElementChild).borderTopLeftRadius);
}

function intersects(rect: DOMRect, container: DOMRect): boolean {
    return (
        rect.right > container.left &&
        rect.left < container.right &&
        rect.bottom > container.top &&
        rect.top < container.bottom
    );
}

function toLocalRect(rect: DOMRect, boardRect: DOMRect): PixelRect {
    return { left: rect.left - boardRect.left, top: rect.top - boardRect.top, width: rect.width, height: rect.height };
}

/** Ratio between the node's on-screen width and its layout width, i.e. the canvas zoom. */
function zoomScale(nodeElement: HTMLElement, nodeRect: DOMRect): number {
    return nodeElement.offsetWidth > 0 ? nodeRect.width / nodeElement.offsetWidth : 1;
}

function parsePixelLength(value: string): number {
    return value.trim().endsWith('px') ? parseFloat(value) || 0 : 0;
}
