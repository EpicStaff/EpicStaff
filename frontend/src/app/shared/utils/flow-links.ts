export function flowUrl(flowId: number | string): string {
  return `/flows/${Number(flowId)}`;
}