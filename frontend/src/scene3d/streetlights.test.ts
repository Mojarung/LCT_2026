import { describe, expect, it } from 'vitest';

import { lampAngle } from './streetlights';

describe('консоль фонаря', () => {
  it('к борту, но не над крышей дома: занятое направление сменяется обратным', () => {
    // Опора в метре от дома (дом - z < -1), борт за домом на z = -20.
    const curb = {
      points: [
        { x: -10, z: -20 },
        { x: 10, z: -20 },
      ],
    };
    const house = (p: { x: number; z: number }) => p.z < -1 && p.z > -15;
    const angle = lampAngle({ x: 0, z: 0 }, [curb], house);
    expect(Math.cos(angle)).toBeCloseTo(1, 6);
    // Без дома - прямо к борту.
    expect(Math.cos(lampAngle({ x: 0, z: 0 }, [curb], () => false))).toBeCloseTo(-1, 6);
  });
});
