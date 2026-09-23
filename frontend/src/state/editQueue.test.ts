import { describe, expect, it } from 'vitest';

import { EditQueue } from './editQueue';

const later = <T>(value: T, ms: number) =>
  new Promise<T>((resolve) => {
    setTimeout(() => {
      resolve(value);
    }, ms);
  });

describe('очередь правок', () => {
  it('следующая правка уходит только после ответа на предыдущую', async () => {
    const queue = new EditQueue();
    const log: string[] = [];
    const first = queue.enqueue(async () => {
      log.push('первая ушла');
      const answer = await later('первая', 30);
      log.push('первая вернулась');
      return answer;
    });
    const second = queue.enqueue(async () => {
      log.push('вторая ушла');
      const answer = await later('вторая', 1);
      log.push('вторая вернулась');
      return answer;
    });

    await expect(Promise.all([first, second])).resolves.toEqual(['первая', 'вторая']);
    expect(log).toEqual(['первая ушла', 'первая вернулась', 'вторая ушла', 'вторая вернулась']);
  });

  it('упавшая правка не останавливает очередь', async () => {
    const queue = new EditQueue();
    const failed = queue.enqueue(() => Promise.reject(new Error('сеть моргнула')));
    const next = queue.enqueue(() => Promise.resolve('дошла'));

    await expect(failed).rejects.toThrow('сеть моргнула');
    await expect(next).resolves.toBe('дошла');
  });
});
