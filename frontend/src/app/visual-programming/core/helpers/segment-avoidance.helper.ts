import { IPoint } from '@foblex/2d';

import { NodeType } from '../enums/node-type';
import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { ViewPort } from '../models/port.model';
import { computeBackwardArcPoints } from './backward-arc.path-builder';
import { isBackwardConnection } from './helpers';
import { getCollisionBounds } from './node-placement.utils';

const GAP = 40;
const ROUTING_PAD = 15;
const TABLE_TOP_CLEARANCE = 68;
const TABLE_TARGET_ENTRY_PAD = 10;
const SOURCE_EXIT_CLEARANCE = 40;
const NODE_CLEARANCE = 24;

function getNodeRect(node: NodeModel) {
    const b = getCollisionBounds(node);
    return {
        nLeft: node.position.x + b.offsetX - ROUTING_PAD,
        nTop: node.position.y + b.offsetY - ROUTING_PAD,
        nRight: node.position.x + b.offsetX + b.width + ROUTING_PAD,
        nBottom: node.position.y + b.offsetY + b.height + ROUTING_PAD,
    };
}

export function getPortPosition(node: NodeModel, port: ViewPort | undefined): IPoint {
    const { x, y } = node.position;
    const { width, height } = node.size;

    let result: IPoint;

    if (node.type === NodeType.TABLE && port) {
        const headerH = 50;
        const bodyH = height - headerH;
        const rowH = bodyH / 3;

        let portY = y + height / 2;

        if (port.id?.includes('table-in')) {
            portY = y + headerH + bodyH / 2;
            result = { x, y: portY };
        } else if (port.id?.includes('decision-default')) {
            portY = y + headerH + rowH * 1.5 - 10;
            result = { x: x + width, y: portY };
        } else if (port.id?.includes('decision-error')) {
            portY = y + headerH + rowH * 2.5 - 6;
            result = { x: x + width, y: portY };
        } else {
            result =
                port.position === 'right'
                    ? { x: x + width, y: y + height / 2 }
                    : port.position === 'top'
                      ? { x: x + width / 2, y }
                      : port.position === 'bottom'
                        ? { x: x + width / 2, y: y + height }
                        : { x, y: y + height / 2 };
        }
    } else {
        switch (port?.position) {
            case 'right':
                result = { x: x + width, y: y + height / 2 };
                break;
            case 'top':
                result = { x: x + width / 2, y };
                break;
            case 'bottom':
                result = { x: x + width / 2, y: y + height };
                break;
            default:
                result = { x, y: y + height / 2 };
                break;
        }
    }

    return result;
}

function pointInRect(p: IPoint, rect: { nLeft: number; nTop: number; nRight: number; nBottom: number }): boolean {
    return p.x >= rect.nLeft && p.x <= rect.nRight && p.y >= rect.nTop && p.y <= rect.nBottom;
}

function orientation(a: IPoint, b: IPoint, c: IPoint): number {
    const value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);

    if (Math.abs(value) < 0.0001) return 0;

    return value > 0 ? 1 : 2;
}

function onSegment(a: IPoint, b: IPoint, c: IPoint): boolean {
    return (
        b.x <= Math.max(a.x, c.x) + 0.0001 &&
        b.x >= Math.min(a.x, c.x) - 0.0001 &&
        b.y <= Math.max(a.y, c.y) + 0.0001 &&
        b.y >= Math.min(a.y, c.y) - 0.0001
    );
}

function segmentsIntersect(p1: IPoint, q1: IPoint, p2: IPoint, q2: IPoint): boolean {
    const o1 = orientation(p1, q1, p2);
    const o2 = orientation(p1, q1, q2);
    const o3 = orientation(p2, q2, p1);
    const o4 = orientation(p2, q2, q1);

    if (o1 !== o2 && o3 !== o4) return true;

    if (o1 === 0 && onSegment(p1, p2, q1)) return true;
    if (o2 === 0 && onSegment(p1, q2, q1)) return true;
    if (o3 === 0 && onSegment(p2, p1, q2)) return true;
    if (o4 === 0 && onSegment(p2, q1, q2)) return true;

    return false;
}

function segmentIntersectsRect(
    a: IPoint,
    b: IPoint,
    rect: { nLeft: number; nTop: number; nRight: number; nBottom: number }
): boolean {
    if (pointInRect(a, rect) || pointInRect(b, rect)) return true;

    const topLeft: IPoint = { x: rect.nLeft, y: rect.nTop };
    const topRight: IPoint = { x: rect.nRight, y: rect.nTop };
    const bottomLeft: IPoint = { x: rect.nLeft, y: rect.nBottom };
    const bottomRight: IPoint = { x: rect.nRight, y: rect.nBottom };

    return (
        segmentsIntersect(a, b, topLeft, topRight) ||
        segmentsIntersect(a, b, topRight, bottomRight) ||
        segmentsIntersect(a, b, bottomRight, bottomLeft) ||
        segmentsIntersect(a, b, bottomLeft, topLeft)
    );
}

function countPathIntersections(path: IPoint[], allNodes: NodeModel[], excludeIds: string[]): number {
    const lastSeg = path.length - 2;
    let count = 0;

    for (const node of allNodes) {
        if (node.type === NodeType.NOTE) continue;
        if (excludeIds.includes(node.id)) continue;
        const rect = getNodeRect(node);

        for (let i = 0; i <= lastSeg; i++) {
            if (segmentIntersectsRect(path[i], path[i + 1], rect)) {
                count++;
                break;
            }
        }
    }

    return count;
}

function pathIntersectsNode(path: IPoint[], node: NodeModel): boolean {
    const rect = getNodeRect(node);

    for (let i = 0; i < path.length - 1; i++) {
        if (segmentIntersectsRect(path[i], path[i + 1], rect)) {
            return true;
        }
    }

    return false;
}

function simplifyRoute(points: IPoint[]): IPoint[] {
    if (points.length <= 2) return points;

    const result: IPoint[] = [points[0]];

    for (let i = 1; i < points.length - 1; i++) {
        const prev = result[result.length - 1];
        const curr = points[i];
        const next = points[i + 1];

        const sameX = prev.x === curr.x && curr.x === next.x;
        const sameY = prev.y === curr.y && curr.y === next.y;

        if (!sameX && !sameY) {
            result.push(curr);
        }
    }

    result.push(points[points.length - 1]);
    return result;
}

function findSegmentBlockers(a: IPoint, b: IPoint, allNodes: NodeModel[], excludeIds: string[]): NodeModel[] {
    const result: NodeModel[] = [];

    for (const node of allNodes) {
        if (excludeIds.includes(node.id)) continue;
        if (node.type === NodeType.NOTE) continue;

        const rect = getNodeRect(node);

        if (segmentIntersectsRect(a, b, rect)) {
            result.push(node);
        }
    }

    return result;
}

function findSegmentNearBlockers(
    a: IPoint,
    b: IPoint,
    allNodes: NodeModel[],
    excludeIds: string[],
    clearance: number
): NodeModel[] {
    const result: NodeModel[] = [];

    for (const node of allNodes) {
        if (excludeIds.includes(node.id)) continue;
        if (node.type === NodeType.NOTE) continue;

        const r = getNodeRect(node);
        const expanded = {
            nLeft: r.nLeft - clearance,
            nTop: r.nTop - clearance,
            nRight: r.nRight + clearance,
            nBottom: r.nBottom + clearance,
        };

        if (segmentIntersectsRect(a, b, expanded)) {
            result.push(node);
        }
    }

    return result;
}

function pathCost(pts: IPoint[]): number {
    const bends = pts.length - 2;
    const manhattan = pts
        .slice(0, -1)
        .reduce((s, p, i) => s + Math.abs(pts[i + 1].x - p.x) + Math.abs(pts[i + 1].y - p.y), 0);
    return bends * 10_000 + manhattan;
}

function buildHDetour(
    path: IPoint[],
    segIdx: number,
    blockers: NodeModel[],
    allNodes: NodeModel[],
    excludeIds: string[]
): IPoint[] | null {
    const a = path[segIdx];
    const b = path[segIdx + 1];
    if (Math.abs(b.y - a.y) > Math.abs(b.x - a.x)) return null;

    const sorted = [...blockers].sort(
        (p, q) => Math.abs(getNodeRect(p).nLeft - a.x) - Math.abs(getNodeRect(q).nLeft - a.x)
    );
    const blocker = sorted[0];
    if (!blocker) return null;

    const br = getNodeRect(blocker);

    let replaceStart = segIdx;
    let replaceEnd = segIdx + 1;

    let left = a;
    let right = b;

    const prev = path[segIdx - 1];
    const next = path[segIdx + 2];

    // absorb left shoulder: prev -> a is horizontal on same Y
    if (prev && prev.y === a.y) {
        replaceStart = segIdx - 1;
        left = prev;
    }

    // absorb right shoulder: b -> next is horizontal on same Y
    if (next && next.y === b.y) {
        replaceEnd = segIdx + 2;
        right = next;
    }

    const valid: IPoint[][] = [];
    const currentScore = countPathIntersections(path, allNodes, excludeIds);

    for (const routeY of [br.nTop - GAP, br.nBottom + GAP]) {
        const candidate = simplifyRoute([
            ...path.slice(0, replaceStart),
            { x: left.x, y: left.y },
            { x: left.x, y: routeY },
            { x: right.x, y: routeY },
            { x: right.x, y: right.y },
            ...path.slice(replaceEnd + 1),
        ]);

        const candidateScore = countPathIntersections(candidate, allNodes, excludeIds);

        const clearsChosenBlocker = !pathIntersectsNode(candidate, blocker);

        if (candidateScore < currentScore || (candidateScore === currentScore && clearsChosenBlocker)) {
            valid.push(candidate);
        }
    }

    if (valid.length === 0) return null;
    return valid.reduce((best, c) => (pathCost(c) < pathCost(best) ? c : best));
}

function buildVDetour(
    path: IPoint[],
    segIdx: number,
    blockers: NodeModel[],
    allNodes: NodeModel[],
    excludeIds: string[]
): IPoint[] | null {
    const a = path[segIdx];
    const b = path[segIdx + 1];
    const goingDown = a.y <= b.y;

    // Process only the closest blocker to 'a' along the segment direction.
    // Merging all blockers into one union produces an entryY that spans multiple
    // nodes, which makes the horizontal legs unvalidatable and cascades into the
    // staircase explosion. Each pass handles one blocker; remaining ones are caught
    // in subsequent passes.
    const sorted = [...blockers].sort((p, q) => {
        const rp = getNodeRect(p);
        const rq = getNodeRect(q);
        return goingDown ? rp.nTop - rq.nTop : rq.nBottom - rp.nBottom;
    });

    const blocker = sorted[0];
    if (!blocker) return null;

    const { nLeft, nTop, nRight, nBottom } = getNodeRect(blocker);

    const baseX = a.x;
    const PAD = 8;

    const ya = Math.min(a.y, b.y);
    const yb = Math.max(a.y, b.y);

    // Overlap interval between the segment and the blocker.
    const overlapTop = Math.max(ya, nTop);
    const overlapBottom = Math.min(yb, nBottom);

    if (overlapTop >= overlapBottom) return null;

    // Entry/exit points hug the blocker bounds with a small pad.
    let entryY = goingDown ? overlapTop - PAD : overlapBottom + PAD;
    let exitY = goingDown ? overlapBottom + PAD : overlapTop - PAD;

    // Push entryY/exitY outside any excluded node's (source/target) y-range so
    // the horizontal bypass legs don't deterministically cross them.
    const excludedRects = excludeIds
        .map((id) => allNodes.find((n) => n.id === id))
        .filter((n): n is NodeModel => n != null)
        .map(getNodeRect);

    for (const r of excludedRects) {
        if (entryY >= r.nTop && entryY <= r.nBottom) {
            entryY = goingDown ? r.nTop - PAD : r.nBottom + PAD;
        }
        if (exitY >= r.nTop && exitY <= r.nBottom) {
            exitY = goingDown ? r.nBottom + PAD : r.nTop - PAD;
        }
    }

    // After clamping the bypass interval may have collapsed or inverted — bail out.
    if (goingDown ? entryY >= exitY : entryY <= exitY) return null;

    // Entry/exit must stay within the segment's y range. The excluded-rects
    // adjustment above can push them outside when the blocker is adjacent to
    // source/target, producing geometrically invalid near-port bypass legs.
    if (entryY < ya || entryY > yb || exitY < ya || exitY > yb) return null;

    // Two candidates: just outside each side of the collision bounds.
    // Always try right first so that multiple blockers on the same segment
    // all bypass to the same side — prevents staircase from alternating directions.
    const rightX = nRight + PAD;
    const leftX = nLeft - PAD;

    const currentScore = countPathIntersections(path, allNodes, excludeIds);

    const makeBypass = (detourX: number): IPoint[] | null => {
        const bypass: IPoint[] = [
            { x: baseX, y: entryY },
            { x: detourX, y: entryY },
            { x: detourX, y: exitY },
            { x: baseX, y: exitY },
        ];

        const candidate = simplifyRoute([...path.slice(0, segIdx + 1), ...bypass, ...path.slice(segIdx + 1)]);

        const candidateScore = countPathIntersections(candidate, allNodes, excludeIds);
        const clearsChosenBlocker = !pathIntersectsNode(candidate, blocker);

        return candidateScore < currentScore || (candidateScore === currentScore && clearsChosenBlocker)
            ? candidate
            : null;
    };

    const validCandidates: Array<{ result: IPoint[]; dist: number }> = [];
    for (const [detourX, dist] of [
        [rightX, Math.abs(rightX - baseX)],
        [leftX, Math.abs(leftX - baseX)],
    ] as [number, number][]) {
        const r = makeBypass(detourX);
        if (r) validCandidates.push({ result: r, dist });
    }

    if (validCandidates.length === 0) return null;
    return validCandidates.sort((a, b) => a.dist - b.dist)[0].result;
}

export function computeSegmentAvoidanceWaypoints(
    connection: ConnectionModel,
    allNodes: NodeModel[],
    existingWaypoints?: IPoint[],
    _allowFreshFallback = true
): IPoint[] | null {
    const sourceNode = allNodes.find((n) => n.id === connection.sourceNodeId);
    const targetNode = allNodes.find((n) => n.id === connection.targetNodeId);

    if (!sourceNode || !targetNode) return null;

    const sourcePort = sourceNode.ports?.find((p) => p.id === connection.sourcePortId);
    const targetPort = targetNode.ports?.find((p) => p.id === connection.targetPortId);

    if (
        sourcePort?.position === 'top' ||
        sourcePort?.position === 'bottom' ||
        targetPort?.position === 'top' ||
        targetPort?.position === 'bottom'
    ) {
        return null;
    }

    const sourcePt = getPortPosition(sourceNode, sourcePort);
    const targetPt = getPortPosition(targetNode, targetPort);
    const excludeIds = [connection.sourceNodeId, connection.targetNodeId];

    const sourceRect = getNodeRect(sourceNode);
    const targetRect = getNodeRect(targetNode);

    const intersectsTableTopProtectedZone = (points: IPoint[]): boolean => {
        if (targetNode.type !== NodeType.TABLE) return false;
        if (points.length < 2) return false;
        const protectedBottom = targetPt.y - TABLE_TARGET_ENTRY_PAD;
        if (protectedBottom <= targetRect.nTop) return false;

        const protectedRect = {
            nLeft: targetRect.nLeft,
            nRight: targetRect.nRight,
            nTop: targetRect.nTop - TABLE_TOP_CLEARANCE,
            nBottom: protectedBottom,
        };

        for (let i = 0; i < points.length - 1; i++) {
            if (segmentIntersectsRect(points[i], points[i + 1], protectedRect)) {
                return true;
            }
        }

        return false;
    };

    const isTableTargetTopSafe = (points: IPoint[]): boolean => !intersectsTableTopProtectedZone(points);

    const isSourceExitSafe = (points: IPoint[]): boolean => {
        if (sourcePort?.position !== 'right') return true;
        if (points.length < 3) return true;

        for (let i = 1; i < points.length - 1; i++) {
            const a = points[i];
            const b = points[i + 1];

            if (a.x !== b.x) continue;
            if (a.y === b.y) continue;

            const dropStartsTooCloseToSource = a.x < sourceRect.nRight + SOURCE_EXIT_CLEARANCE;

            const goesBelowOutputLevel = Math.max(a.y, b.y) > sourcePt.y;

            if (dropStartsTooCloseToSource && goesBelowOutputLevel) {
                return false;
            }

            return true;
        }

        return true;
    };

    const intersectsSourceTableTopZone = (points: IPoint[]): boolean => {
        if (sourceNode.type !== NodeType.TABLE) return false;
        if (sourcePort?.position !== 'right') return false;
        if (points.length < 2) return false;

        const TOP_PORT_BUFFER = 40;

        const protectedBottom = sourcePt.y - TOP_PORT_BUFFER;
        if (protectedBottom <= sourceRect.nTop) return false;

        const protectedRect = {
            nLeft: sourceRect.nLeft,
            nRight: sourceRect.nRight + ROUTING_PAD,
            nTop: sourceRect.nTop,
            nBottom: protectedBottom,
        };

        for (let i = 0; i < points.length - 1; i++) {
            const hit = segmentIntersectsRect(points[i], points[i + 1], protectedRect);

            if (hit) {
                return true;
            }
        }

        return false;
    };

    const isSourceTableTopSafe = (points: IPoint[]): boolean => !intersectsSourceTableTopZone(points);

    const portAdjacentIds = allNodes
        .filter((n) => !excludeIds.includes(n.id) && n.type !== NodeType.NOTE)
        .filter((n) => {
            const r = getNodeRect(n);
            return pointInRect(sourcePt, r) || pointInRect(targetPt, r);
        })
        .map((n) => n.id);

    const defaultMidX = (sourcePt.x + targetPt.x) / 2;
    const ya = Math.min(sourcePt.y, targetPt.y);
    const yb = Math.max(sourcePt.y, targetPt.y);
    const corridorPad = 8;

    const vertBlockers = allNodes.filter((n) => {
        if (excludeIds.includes(n.id)) return false;
        if (n.type === NodeType.NOTE) return false;
        const r = getNodeRect(n);
        return r.nLeft < defaultMidX && r.nRight > defaultMidX && r.nTop < yb && r.nBottom > ya;
    });

    const isXFree = (x: number): boolean =>
        allNodes.every((n) => {
            if (excludeIds.includes(n.id) || n.type === NodeType.NOTE) return true;
            const r = getNodeRect(n);
            if (r.nTop >= yb || r.nBottom <= ya) return true;
            return x <= r.nLeft || x >= r.nRight;
        });

    let midX = defaultMidX;
    let proactiveShift = false;
    if (vertBlockers.length > 0) {
        const candidates: number[] = [];
        for (const n of vertBlockers) {
            const r = getNodeRect(n);
            candidates.push(r.nRight + corridorPad);
            candidates.push(r.nLeft - corridorPad);
        }
        const free = candidates.filter(isXFree);
        if (free.length > 0) {
            const forwardFree = free.filter((x) => (targetPt.x >= sourcePt.x ? x >= sourcePt.x : x <= sourcePt.x));
            const inRangeFree = forwardFree.filter((x) =>
                targetPt.x >= sourcePt.x ? x <= targetPt.x : x >= targetPt.x
            );
            if (inRangeFree.length > 0) {
                midX = inRangeFree.reduce((best, x) =>
                    Math.abs(x - defaultMidX) < Math.abs(best - defaultMidX) ? x : best
                );
                proactiveShift = midX !== defaultMidX;
            }
        }
    }

    const scoreBasePath: IPoint[] =
        existingWaypoints && existingWaypoints.length > 0
            ? simplifyRoute([sourcePt, ...existingWaypoints, targetPt])
            : simplifyRoute([sourcePt, { x: defaultMidX, y: sourcePt.y }, { x: defaultMidX, y: targetPt.y }, targetPt]);

    const startScore = countPathIntersections(scoreBasePath, allNodes, excludeIds);

    const startHasNearBlockers = scoreBasePath.some((_, idx, arr) => {
        if (idx === arr.length - 1) return false;
        return findSegmentNearBlockers(arr[idx], arr[idx + 1], allNodes, excludeIds, NODE_CLEARANCE).length > 0;
    });

    if (startScore === 0 && !startHasNearBlockers) {
        if (existingWaypoints && existingWaypoints.length > 0) {
            const defaultPath = simplifyRoute([
                sourcePt,
                { x: defaultMidX, y: sourcePt.y },
                { x: defaultMidX, y: targetPt.y },
                targetPt,
            ]);
            const defaultScore = countPathIntersections(defaultPath, allNodes, excludeIds);
            return defaultScore === 0 ? [] : null;
        }
        return null;
    }

    let path: IPoint[];
    if (existingWaypoints && existingWaypoints.length > 0) {
        path = simplifyRoute([sourcePt, ...existingWaypoints, targetPt]);
    } else {
        path = simplifyRoute([sourcePt, { x: midX, y: sourcePt.y }, { x: midX, y: targetPt.y }, targetPt]);
    }

    let hadDetour = (existingWaypoints && existingWaypoints.length > 0) || proactiveShift;

    for (let pass = 0; pass < 6; pass++) {
        let changed = false;

        for (let i = path.length - 2; i >= 0; i--) {
            const a = path[i];
            const b = path[i + 1];

            const isFirstSeg = i === 0;
            const isLastSeg = i === path.length - 2;

            const segmentExcludeIds =
                (isFirstSeg || isLastSeg) && portAdjacentIds.length > 0
                    ? [...excludeIds, ...portAdjacentIds]
                    : excludeIds;

            const strictBlockers = findSegmentBlockers(a, b, allNodes, segmentExcludeIds);
            const nearBlockers =
                strictBlockers.length > 0
                    ? []
                    : findSegmentNearBlockers(a, b, allNodes, segmentExcludeIds, NODE_CLEARANCE);

            const segBlockers = strictBlockers.length > 0 ? strictBlockers : nearBlockers;
            if (!segBlockers.length) continue;

            const detourPts =
                a.y === b.y
                    ? buildHDetour(path, i, segBlockers, allNodes, segmentExcludeIds)
                    : buildVDetour(path, i, segBlockers, allNodes, segmentExcludeIds);

            if (detourPts) {
                path = detourPts;
                changed = true;
                hadDetour = true;
            } else if (a.x === b.x) {
                const br = getNodeRect(segBlockers[0]);
                const spineCandidates = [br.nRight + corridorPad, br.nLeft - corridorPad];

                for (const newMidX of spineCandidates) {
                    if (!isXFree(newMidX)) continue;

                    const rebuilt = simplifyRoute([
                        sourcePt,
                        { x: newMidX, y: sourcePt.y },
                        { x: newMidX, y: targetPt.y },
                        targetPt,
                    ]);
                    const rebuiltScore = countPathIntersections(rebuilt, allNodes, excludeIds);

                    const minX = Math.min(sourcePt.x, targetPt.x) - corridorPad;
                    const maxX = Math.max(sourcePt.x, targetPt.x) + corridorPad;

                    if (rebuiltScore === 0 && newMidX >= minX && newMidX <= maxX) {
                        path = rebuilt;
                        changed = true;
                        hadDetour = true;
                        break;
                    }
                }

                // If no clean 4-point spine was found, try 6-point paths that route
                // around the blocker above or below it rather than through its corridor.
                if (!changed) {
                    const sourceRect = getNodeRect(sourceNode);
                    const targetRect = getNodeRect(targetNode);
                    const x1 = sourceRect.nRight + corridorPad;
                    const x2 = targetRect.nLeft - corridorPad;
                    let x1Adj = x1;
                    let x2Adj = x2;
                    if (x1Adj > br.nLeft && x1Adj < br.nRight) x1Adj = br.nRight + corridorPad;
                    if (x2Adj > br.nLeft && x2Adj < br.nRight) x2Adj = br.nLeft - corridorPad;

                    if (x1Adj !== x2Adj) {
                        const sixPtCandidates = [
                            simplifyRoute([
                                sourcePt,
                                { x: x1Adj, y: sourcePt.y },
                                { x: x1Adj, y: br.nTop - GAP },
                                { x: x2Adj, y: br.nTop - GAP },
                                { x: x2Adj, y: targetPt.y },
                                targetPt,
                            ]),
                            simplifyRoute([
                                sourcePt,
                                { x: x1Adj, y: sourcePt.y },
                                { x: x1Adj, y: br.nBottom + GAP },
                                { x: x2Adj, y: br.nBottom + GAP },
                                { x: x2Adj, y: targetPt.y },
                                targetPt,
                            ]),
                        ];

                        for (const candidate6 of sixPtCandidates) {
                            const rebuiltScore = countPathIntersections(candidate6, allNodes, excludeIds);

                            if (rebuiltScore === 0) {
                                path = candidate6;
                                changed = true;
                                hadDetour = true;
                                break;
                            }
                        }
                    }
                }

                if (changed) break; // restart inner loop on the rebuilt spine next pass
            }
        }

        path = simplifyRoute(path);

        if (!changed) break;
    }

    if (!hadDetour) return null;

    const interiorWaypoints = path.slice(1, -1);
    const fullPath = [sourcePt, ...interiorWaypoints, targetPt];

    fullPath.forEach((p, idx) => {
        if (idx < fullPath.length - 1) {
            const q = fullPath[idx + 1];
            console.log(
                `  p${idx}→p${idx + 1} : (${p.x.toFixed(1)},${p.y.toFixed(1)}) → (${q.x.toFixed(1)},${q.y.toFixed(1)})`
            );
        }
    });

    // ── Score the final path and return only if it improves on startScore ────────────
    const finalScore = countPathIntersections(
        [sourcePt, ...interiorWaypoints, targetPt],
        allNodes,
        portAdjacentIds.length > 0 ? [...excludeIds, ...portAdjacentIds] : excludeIds
    );

    const tableTargetTopSafe = isTableTargetTopSafe(fullPath);
    const sourceExitSafe = isSourceExitSafe(fullPath);
    const sourceTableTopSafe = isSourceTableTopSafe(fullPath);

    if (finalScore === 0 && tableTargetTopSafe && sourceExitSafe && sourceTableTopSafe) {
        if (interiorWaypoints.length > 0) {
            const penultimate = interiorWaypoints[interiorWaypoints.length - 1];
            if (penultimate.y === targetPt.y) {
                const targetIsLeftPort = targetPort?.position !== 'right';
                if (targetIsLeftPort ? penultimate.x > targetPt.x : penultimate.x < targetPt.x) {
                    return null;
                }
            }

            const second = interiorWaypoints[0];
            if (second.y === sourcePt.y) {
                const sourceIsRightPort = sourcePort?.position === 'right';
                if (sourceIsRightPort ? second.x < sourcePt.x : second.x > sourcePt.x) {
                    return null;
                }
            }
        }
        return interiorWaypoints;
    }

    if (_allowFreshFallback && existingWaypoints && existingWaypoints.length > 0) {
        const defaultPath = simplifyRoute([sourcePt, { x: midX, y: sourcePt.y }, { x: midX, y: targetPt.y }, targetPt]);
        const defaultPathScore = countPathIntersections(defaultPath, allNodes, excludeIds);
        if (defaultPathScore === 0) return []; // blocker moved off the default spine; restore it
        return computeSegmentAvoidanceWaypoints(connection, allNodes, undefined, false);
    }

    return null; // no improvement — caller must keep existing waypoints unchanged
}

export function getConnectionRenderedPath(connection: ConnectionModel, allNodes: NodeModel[]): IPoint[] | null {
    const sourceNode = allNodes.find((n) => n.id === connection.sourceNodeId);
    const targetNode = allNodes.find((n) => n.id === connection.targetNodeId);
    if (!sourceNode || !targetNode) return null;

    const sourcePort = sourceNode.ports?.find((p) => p.id === connection.sourcePortId);
    const targetPort = targetNode.ports?.find((p) => p.id === connection.targetPortId);

    const sourcePt = getPortPosition(sourceNode, sourcePort);
    const targetPt = getPortPosition(targetNode, targetPort);

    if (isBackwardConnection(connection, allNodes)) {
        return computeBackwardArcPoints(sourcePt, targetPt, connection.waypoints, allNodes);
    }

    if (connection.waypoints && connection.waypoints.length > 0) {
        return simplifyRoute([sourcePt, ...connection.waypoints, targetPt]);
    }

    const defaultMidX = (sourcePt.x + targetPt.x) / 2;
    return simplifyRoute([sourcePt, { x: defaultMidX, y: sourcePt.y }, { x: defaultMidX, y: targetPt.y }, targetPt]);
}

export function getConnectionIntersectingNodes(
    connection: ConnectionModel,
    allNodes: NodeModel[],
    padding = 0
): NodeModel[] {
    const path = getConnectionRenderedPath(connection, allNodes);
    if (!path || path.length < 2) return [];

    const excludeIds = [connection.sourceNodeId, connection.targetNodeId];
    const result: NodeModel[] = [];

    for (const node of allNodes) {
        if (excludeIds.includes(node.id)) continue;
        if (node.type === NodeType.NOTE) continue;

        const r = getNodeRect(node);
        const rect =
            padding === 0
                ? r
                : {
                      nLeft: r.nLeft - padding,
                      nTop: r.nTop - padding,
                      nRight: r.nRight + padding,
                      nBottom: r.nBottom + padding,
                  };

        for (let i = 0; i < path.length - 1; i++) {
            if (segmentIntersectsRect(path[i], path[i + 1], rect)) {
                result.push(node);
                break;
            }
        }
    }

    return result;
}

export function normalizeConnectionWaypoints(
    connection: ConnectionModel,
    allNodes: NodeModel[],
    waypoints: IPoint[] | undefined
): IPoint[] {
    const sourceNode = allNodes.find((n) => n.id === connection.sourceNodeId);
    const targetNode = allNodes.find((n) => n.id === connection.targetNodeId);

    if (!sourceNode || !targetNode) {
        return waypoints ?? [];
    }

    const sourcePort = sourceNode.ports?.find((p) => p.id === connection.sourcePortId);
    const targetPort = targetNode.ports?.find((p) => p.id === connection.targetPortId);

    const sourcePt = getPortPosition(sourceNode, sourcePort);
    const targetPt = getPortPosition(targetNode, targetPort);

    const raw = waypoints ?? [];

    if (isBackwardConnection(connection, allNodes)) {
        return raw;
    }

    const simplified = simplifyRoute([sourcePt, ...raw, targetPt]);

    return simplified.slice(1, -1);
}
