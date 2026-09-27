/* Доступ к движку карты из панелей: кнопки масштаба, «вписать», разворот, выбор из списка. */

import { createContext, useContext, type RefObject } from 'react';

import type { PlanEngine } from '../map/engine';

export const EngineContext = createContext<RefObject<PlanEngine | null> | null>(null);

export function useEngine(): RefObject<PlanEngine | null> {
  const ref = useContext(EngineContext);
  if (!ref) throw new Error('useEngine вне EngineContext');
  return ref;
}
