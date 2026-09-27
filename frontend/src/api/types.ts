/* Типы ответов API из сгенерированной схемы (npm run gen:api по docs/openapi.json). */

import type { components } from './schema';

type Schemas = components['schemas'];

export type RunOut = Schemas['RunOut'];
export type RunState = RunOut['state'];
export type ProgressOut = Schemas['ProgressOut'];
export type StepOut = Schemas['StepOut'];
export type ArtifactOut = Schemas['ArtifactOut'];
export type MetaOut = Schemas['MetaOut'];
export type StreetOut = Schemas['StreetOut'];
export type ProfileOut = Schemas['ProfileOut'];
export type CheckOut = Schemas['CheckOut'];
export type EditIn = Schemas['EditIn'];
export type PlanSummaryOut = Schemas['PlanSummaryOut'];
export type RunListOut = Schemas['RunListOut'];
