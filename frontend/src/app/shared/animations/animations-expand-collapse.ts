import {
  trigger,
  state,
  style,
  animate,
  transition,
} from '@angular/animations';

export const expandCollapseAnimation = trigger('expandCollapse', [
  state(
    'collapsed',
    style({
      maxHeight: '0',
      opacity: '0',
      visibility: 'hidden',
    })
  ),
  state(
    'expanded',
    style({
      maxHeight: '1000px',
      opacity: '1',
      visibility: 'visible',
    })
  ),
  transition('expanded <=> collapsed', [animate('180ms ease-in-out')]),
]);
